"""Human-readable job labels from submission snapshots, never mutable templates."""


def snapshot_job_names(template, action, params):
    from services.creative_format import normalize_creative_format
    names = {"campaign_name": template.name, "ad_names": []}
    if action != "CREATE":
        return names
    config = template.creative_config_json or {}
    groups = config.get("adsets") or [{}]
    if params.get("ad_group_mode") == "EXISTING":
        groups = groups[:1]
    for group_index, group in enumerate(groups, 1):
        creatives = group.get("creatives") or config.get("creatives") or [config]
        if normalize_creative_format(config.get("creative_format")) == "CAROUSEL":
            creatives = [config]
        names["ad_names"].extend(
            f"{template.name} G{group_index} A{index}"
            for index in range(1, len(creatives) + 1)
        )
    return names


def job_display_names(job, items):
    snapshot = (job.params or {}).get("_display_names") or {}
    campaign_names, ad_names = [], []
    for item in items:
        protocol = (item.response_payload or {}).get("protocol") or {}
        campaign = protocol.get("campaign") or {}
        if campaign.get("name"):
            campaign_names.append(campaign["name"])
        for adset in protocol.get("adsets") or []:
            for creative in adset.get("creatives") or []:
                ad_names.extend(ad["name"] for ad in creative.get("ads") or [] if ad.get("name"))
        # Existing operation jobs retain their original instance label.
        if not campaign.get("name") and item.campaign_instance and (
            job.action_type != "CREATE" or not snapshot.get("campaign_name")
        ):
            campaign_names.append(item.campaign_instance.name)
    campaign_name = next(iter(campaign_names), None) or snapshot.get("campaign_name")
    if not campaign_name and job.template:
        campaign_name = job.template.name  # Legacy tasks without a submission snapshot.
    return {
        "campaign_name": campaign_name,
        "ad_names": list(dict.fromkeys(ad_names or snapshot.get("ad_names") or [])),
    }
