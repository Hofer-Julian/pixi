use std::{
    collections::HashMap,
    ffi::OsStr,
    iter,
    path::{Path, PathBuf},
};

use clap::Parser;
use distribution_types::Diagnostic;
use indexmap::IndexMap;
use itertools::Itertools;
use miette::{bail, Context, IntoDiagnostic};
use pixi_utils::reqwest::build_reqwest_clients;
use rattler::{
    install::{DefaultProgressFormatter, IndicatifReporter, Installer},
    package_cache::PackageCache,
};
use rattler_conda_types::{
    GenericVirtualPackage, MatchSpec, PackageName, Platform, PrefixRecord, RepoDataRecord,
};
use rattler_shell::{
    activation::{ActivationVariables, Activator, PathModificationBehavior},
    shell::{Shell, ShellEnum},
};
use rattler_solve::{resolvo::Solver, SolverImpl, SolverTask};
use rattler_virtual_packages::VirtualPackage;
use reqwest_middleware::ClientWithMiddleware;

use crate::{
    cli::cli_config::ChannelsConfig, cli::has_specs::HasSpecs, prefix::Prefix,
    rlimit::try_increase_rlimit_to_sensible,
};
use crate::{
    global::{
        channel_name_from_prefix, find_designated_package, print_executables_available, BinDir,
        BinEnvDir,
    },
    task::ExecutableTask,
};
use pixi_config::{self, Config, ConfigCli};
use pixi_progress::{await_in_progress, global_multi_progress, wrap_in_progress};

use super::EnvironmentName;

/// Sync given global environment records with environment on the system
pub(crate) async fn sync_environment(
    environment_name: &EnvironmentName,
    exposed: &IndexMap<String, String>,
    packages: Vec<PackageName>,
    records: Vec<RepoDataRecord>,
    authenticated_client: ClientWithMiddleware,
    platform: Platform,
    bin_dir: &BinDir,
) -> miette::Result<()> {
    try_increase_rlimit_to_sensible();

    // Create the binary environment prefix where we install or update the package
    let BinEnvDir(bin_prefix) = BinEnvDir::create(environment_name).await?;
    let prefix = Prefix::new(bin_prefix);

    // Install the environment
    let package_cache = PackageCache::new(pixi_config::get_cache_dir()?.join("pkgs"));

    let result = await_in_progress("creating virtual environment", |pb| {
        Installer::new()
            .with_download_client(authenticated_client)
            .with_io_concurrency_limit(100)
            .with_execute_link_scripts(false)
            .with_package_cache(package_cache)
            .with_target_platform(platform)
            .with_reporter(
                IndicatifReporter::builder()
                    .with_multi_progress(global_multi_progress())
                    .with_placement(rattler::install::Placement::After(pb))
                    .with_formatter(DefaultProgressFormatter::default().with_prefix("  "))
                    .clear_when_done(true)
                    .finish(),
            )
            .install(prefix.root(), records)
    })
    .await
    .into_diagnostic()?;

    // Determine the shell to use for the invocation script
    let shell: ShellEnum = if cfg!(windows) {
        rattler_shell::shell::CmdExe.into()
    } else {
        rattler_shell::shell::Bash.into()
    };

    // Construct the reusable activation script for the shell and generate an
    // invocation script for each executable added by the package to the
    // environment.
    let activation_script = create_activation_script(&prefix, shell.clone())?;

    let prefix_records = prefix.find_installed_packages(None).await?;

    /// Processes prefix records to filter and collect executable files.
    /// It performs the following steps:
    /// 1. Filters records to only include direct dependencies
    /// 2. Finds executables for each filtered record.
    /// 3. Maps executables to a tuple of file name (as a string) and file path.
    /// 4. Filters tuples to include only those whose names are in the `exposed` values.
    /// 5. Collects the resulting tuples into a vector of executables.
    let executables: Vec<(String, PathBuf)> = prefix_records
        .into_iter()
        .filter(|record| packages.contains(&record.repodata_record.package_record.name))
        .flat_map(|record| find_executables(&prefix, record))
        .filter_map(|path| {
            path.file_name()
                .and_then(|name| name.to_str())
                .map(|name| (name.to_string(), path.clone()))
        })
        .filter(|(name, path)| exposed.values().contains(&name))
        .collect();

    let script_mapping = exposed
        .into_iter()
        .map(|(exposed_name, entry_point)| {
            script_exec_mapping(
                exposed_name,
                entry_point,
                executables.clone(),
                bin_dir,
                environment_name,
            )
        })
        .collect::<miette::Result<Vec<_>>>()?;

    create_executable_scripts(&script_mapping, &prefix, &shell, activation_script).await?;

    Ok(())
}

/// Maps an entry point in the environment to a concrete `ScriptExecMapping`.
///
/// This function takes an entry point and a list of executable names and paths,
/// and returns a `ScriptExecMapping` that contains the path to the script and
/// the original executable.
/// # Returns
///
/// A `miette::Result` containing the `ScriptExecMapping` if the entry point is found,
/// or an error if it is not.
///
/// # Errors
///
/// Returns an error if the entry point is not found in the list of executable names.
fn script_exec_mapping(
    exposed_name: &str,
    entry_point: &str,
    executables: impl IntoIterator<Item = (String, PathBuf)>,
    bin_dir: &BinDir,
    environment_name: &EnvironmentName,
) -> miette::Result<ScriptExecMapping> {
    executables
        .into_iter()
        .find(|(executable_name, _)| *executable_name == entry_point)
        .map(|(_, executable_path)| ScriptExecMapping {
            global_script_path: bin_dir.executable_script_path(exposed_name),
            original_executable: executable_path,
        })
        .ok_or_else(|| miette::miette!("Could not find {entry_point} in {environment_name}"))
}

/// Create the environment activation script
fn create_activation_script(prefix: &Prefix, shell: ShellEnum) -> miette::Result<String> {
    let activator =
        Activator::from_path(prefix.root(), shell, Platform::current()).into_diagnostic()?;
    let result = activator
        .activation(ActivationVariables {
            conda_prefix: None,
            path: None,
            path_modification_behavior: PathModificationBehavior::Prepend,
        })
        .into_diagnostic()?;

    // Add a shebang on unix based platforms
    let script = if cfg!(unix) {
        format!("#!/bin/sh\n{}", result.script.contents().into_diagnostic()?)
    } else {
        result.script.contents().into_diagnostic()?
    };

    Ok(script)
}

/// Mapping from the global script location to an executable in a package environment .
#[derive(Debug)]
pub struct ScriptExecMapping {
    pub global_script_path: PathBuf,
    pub original_executable: PathBuf,
}

/// Find the executable scripts within the specified package installed in this
/// conda prefix.
fn find_executables(prefix: &Prefix, prefix_package: PrefixRecord) -> Vec<PathBuf> {
    prefix_package
        .files
        .into_iter()
        .filter(|relative_path| is_executable(prefix, relative_path))
        .collect()
}

fn is_executable(prefix: &Prefix, relative_path: &Path) -> bool {
    // Check if the file is in a known executable directory.
    let binary_folders = if cfg!(windows) {
        &([
            "",
            "Library/mingw-w64/bin/",
            "Library/usr/bin/",
            "Library/bin/",
            "Scripts/",
            "bin/",
        ][..])
    } else {
        &(["bin"][..])
    };

    let parent_folder = match relative_path.parent() {
        Some(dir) => dir,
        None => return false,
    };

    if !binary_folders
        .iter()
        .any(|bin_path| Path::new(bin_path) == parent_folder)
    {
        return false;
    }

    // Check if the file is executable
    let absolute_path = prefix.root().join(relative_path);
    is_executable::is_executable(absolute_path)
}

/// Returns the string to add for all arguments passed to the script
fn get_catch_all_arg(shell: &ShellEnum) -> &str {
    match shell {
        ShellEnum::CmdExe(_) => "%*",
        ShellEnum::PowerShell(_) => "@args",
        _ => "\"$@\"",
    }
}

/// For each executable provided, map it to the installation path for its global
/// binary script.
async fn map_executables_to_global_bin_scripts(
    package_executables: impl IntoIterator<Item = PathBuf>,
    bin_dir: &BinDir,
) -> miette::Result<Vec<ScriptExecMapping>> {
    #[cfg(target_family = "windows")]
    let extensions_list: Vec<String> = if let Ok(pathext) = std::env::var("PATHEXT") {
        pathext.split(';').map(|s| s.to_lowercase()).collect()
    } else {
        tracing::debug!("Could not find 'PATHEXT' variable, using a default list");
        [
            ".COM", ".EXE", ".BAT", ".CMD", ".VBS", ".VBE", ".JS", ".JSE", ".WSF", ".WSH", ".MSC",
            ".CPL",
        ]
        .iter()
        .map(|&s| s.to_lowercase())
        .collect()
    };

    #[cfg(target_family = "unix")]
    // TODO: Find if there are more relevant cases, these cases are generated by our big friend
    // GPT-4
    let extensions_list: Vec<String> = vec![
        ".sh", ".bash", ".zsh", ".csh", ".tcsh", ".ksh", ".fish", ".py", ".pl", ".rb", ".lua",
        ".php", ".tcl", ".awk", ".sed",
    ]
    .iter()
    .map(|&s| s.to_owned())
    .collect();

    let BinDir(bin_dir) = bin_dir;
    let mut mappings = vec![];

    for exec in package_executables {
        // Remove the extension of a file if it is in the list of known extensions.
        let Some(file_name) = exec
            .file_name()
            .and_then(OsStr::to_str)
            .map(str::to_lowercase)
        else {
            continue;
        };
        let file_name = extensions_list
            .iter()
            .find_map(|ext| file_name.strip_suffix(ext))
            .unwrap_or(file_name.as_str());

        let mut executable_script_path = bin_dir.join(file_name);

        if cfg!(windows) {
            executable_script_path.set_extension("bat");
        };
        mappings.push(ScriptExecMapping {
            original_executable: exec,
            global_script_path: executable_script_path,
        });
    }
    Ok(mappings)
}

/// Create the executable scripts by modifying the activation script
/// to activate the environment and run the executable.
async fn create_executable_scripts(
    mapped_executables: &[ScriptExecMapping],
    prefix: &Prefix,
    shell: &ShellEnum,
    activation_script: String,
) -> miette::Result<()> {
    for ScriptExecMapping {
        global_script_path,
        original_executable,
    } in mapped_executables
    {
        let mut script = activation_script.clone();
        shell
            .run_command(
                &mut script,
                [
                    format!(
                        "\"{}\"",
                        prefix.root().join(original_executable).to_string_lossy()
                    )
                    .as_str(),
                    get_catch_all_arg(shell),
                ],
            )
            .expect("should never fail");

        if matches!(shell, ShellEnum::CmdExe(_)) {
            // wrap the script contents in `@echo off` and `setlocal` to prevent echoing the
            // script and to prevent leaking environment variables into the
            // parent shell (e.g. PATH would grow longer and longer)
            script = format!("@echo off\nsetlocal\n{}\nendlocal", script);
        }

        tokio::fs::write(&global_script_path, script)
            .await
            .into_diagnostic()?;

        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(global_script_path, std::fs::Permissions::from_mode(0o755))
                .into_diagnostic()?;
        }
    }
    Ok(())
}

/// Warn user on dangerous package installations, interactive yes no prompt
pub(crate) fn prompt_user_to_continue(
    packages: &IndexMap<PackageName, MatchSpec>,
) -> miette::Result<bool> {
    let dangerous_packages = HashMap::from([
        ("pixi", "Installing `pixi` globally doesn't work as expected.\nUse `pixi self-update` to update pixi and `pixi self-update --version x.y.z` for a specific version."),
        ("pip", "Installing `pip` with `pixi global` won't make pip-installed packages globally available.\nInstead, use a pixi project and add PyPI packages with `pixi add --pypi`, which is recommended. Alternatively, `pixi add pip` and use it within the project.")
    ]);

    // Check if any of the packages are dangerous, and prompt the user to ask if
    // they want to continue, including the advice.
    for (name, _spec) in packages {
        if let Some(advice) = dangerous_packages.get(&name.as_normalized()) {
            let prompt = format!(
                "{}\nDo you want to continue?",
                console::style(advice).yellow()
            );
            if !dialoguer::Confirm::new()
                .with_prompt(prompt)
                .default(false)
                .show_default(true)
                .interact()
                .into_diagnostic()?
            {
                return Ok(false);
            }
        }
    }

    Ok(true)
}