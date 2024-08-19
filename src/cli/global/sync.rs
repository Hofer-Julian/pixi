use crate::{cli::cli_config::ChannelsConfig, global};
use clap::Parser;
use itertools::Itertools;
use miette::IntoDiagnostic;
use pixi_config::{Config, ConfigCli};
use pixi_utils::{default_channel_config, reqwest::build_reqwest_clients};
use rattler_conda_types::{MatchSpec, Platform};

/// Sync global manifest with installed environments
#[derive(Parser, Debug)]
#[clap(arg_required_else_help = true)]
pub struct Args {
    #[clap(flatten)]
    config: ConfigCli,
}

/// Sync global manifest with installed environments
pub async fn execute(args: Args) -> miette::Result<()> {
    let config = Config::with_cli_config(&args.config);
    let project = global::Project::discover()?.with_cli_config(config.clone());

    // TODO: also expose other channels
    let channels = ChannelsConfig::default().resolve_from_config(&config);

    // Fetch the repodata
    let (_, auth_client) = build_reqwest_clients(Some(&config));

    let gateway = config.gateway(auth_client.clone());

    let repodata = gateway
        .query(
            channels,
            [Platform::current(), Platform::NoArch],
            // TODO make this more robust and support more than one environment
            project
                .environments()
                .first()
                .unwrap()
                .1
                .dependencies()
                .into_iter()
                .map(|(name, spec)| {
                    MatchSpec::from_nameless(
                        spec.try_into_nameless_match_spec(&default_channel_config())
                            .unwrap()
                            .unwrap(),
                        Some(name),
                    )
                })
                .collect_vec(),
        )
        .recursive(true)
        .await
        .into_diagnostic()?;

    todo!();
    // // Determine virtual packages of the current platform
    // let virtual_packages = VirtualPackage::current()
    //     .into_diagnostic()
    //     .context("failed to determine virtual packages")?
    //     .iter()
    //     .cloned()
    //     .map(GenericVirtualPackage::from)
    //     .collect();

    // // Solve the environment
    // let solver_specs = specs.clone();
    // let solved_records = wrap_in_progress("solving environment", move || {
    //     Solver.solve(SolverTask {
    //         specs: solver_specs.values().cloned().collect_vec(),
    //         virtual_packages,
    //         ..SolverTask::from_iter(&repodata)
    //     })
    // })
    // .into_diagnostic()
    // .context("failed to solve environment")?;

    // // Install the package(s)
    // let mut executables = vec![];
    // for (package_name, _) in specs {
    //     let (prefix_package, scripts, _) = globally_install_package(
    //         &package_name,
    //         solved_records.clone(),
    //         auth_client.clone(),
    //         args.platform,
    //     )
    //     .await?;
    //     let channel_name =
    //         channel_name_from_prefix(&prefix_package, config.global_channel_config());
    //     let record = &prefix_package.repodata_record.package_record;

    //     // Warn if no executables were created for the package
    //     if scripts.is_empty() {
    //         eprintln!(
    //             "{}No executable entrypoint found in package {}, are you sure it exists?",
    //             console::style(console::Emoji("⚠️", "")).yellow().bold(),
    //             console::style(record.name.as_source()).bold()
    //         );
    //     }

    //     eprintln!(
    //         "{}Installed package {} {} {} from {}",
    //         console::style(console::Emoji("✔ ", "")).green(),
    //         console::style(record.name.as_source()).bold(),
    //         console::style(record.version.version()).bold(),
    //         console::style(record.build.as_str()).bold(),
    //         channel_name,
    //     );

    //     executables.extend(scripts);
    // }

    // if !executables.is_empty() {
    //     print_executables_available(executables).await?;
    // }

    // Ok(())
}
