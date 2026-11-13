use pixi_build_ros::{metadata::parse_and_render, package_xml::PackageXml};
use pixi_build_types::ProjectModel;

fn assert_recipe_license(licenses: &[&str], expected: &str) {
    let license_elements = licenses
        .iter()
        .map(|license| format!("<license><![CDATA[{license}]]></license>"))
        .collect::<String>();
    let package = PackageXml::parse(&format!(
        "<package format=\"3\"><name>license_probe</name><version>1.2.3</version>\
         {license_elements}</package>"
    ))
    .unwrap();
    let generated = parse_and_render(
        package,
        "jazzy",
        ProjectModel::default(),
        Vec::new(),
        Vec::new(),
    )
    .unwrap();
    let recipe = serde_json::to_value(&generated.recipe).unwrap();
    assert_eq!(recipe["about"]["license"], expected);
}

#[test]
fn overlapping_license_names_preserve_grouping_and_exceptions() {
    assert_recipe_license(
        &["(LGPL-2.0 OR GPL-2.0 WITH Classpath-exception-2.0) AND (AGPL-3.0 OR GPL-3.0)"],
        "(LGPL-2.0-only OR GPL-2.0-only WITH Classpath-exception-2.0) AND (AGPL-3.0-only OR GPL-3.0-only)",
    );
}

#[test]
fn repeated_licenses_keep_their_own_postfix_plus() {
    assert_recipe_license(
        &["GPL-2.0+ AND GPL-2.0 AND GPL-2.0+ AND MIT+"],
        "GPL-2.0-or-later AND GPL-2.0-only AND GPL-2.0-or-later AND MIT+",
    );
}

#[test]
fn slash_alternatives_survive_recipe_validation() {
    assert_recipe_license(
        &["(LGPL-2.0/GPL-2.0 WITH Classpath-exception-2.0) AND MIT"],
        "(LGPL-2.0-only OR GPL-2.0-only WITH Classpath-exception-2.0) AND MIT",
    );
}

#[test]
fn custom_license_references_preserve_alternatives_and_document_qualifiers() {
    assert_recipe_license(
        &[
            "(GPL-2.0+ OR LicenseRef-Proprietary) AND DocumentRef-vendor:LicenseRef-Terms",
            "LicenseRef-Proprietary",
        ],
        "(GPL-2.0-or-later OR LicenseRef-Proprietary) AND DocumentRef-vendor:LicenseRef-Terms OR LicenseRef-Proprietary",
    );
}
