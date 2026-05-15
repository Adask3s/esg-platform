from backend.celery.report_tasks import _report_filter_candidates


def test_report_filter_candidates_include_frontend_tag_aliases():
    assert _report_filter_candidates("Environmental") == [
        "Environmental",
        "environmental",
        "E",
        "e",
    ]
    assert _report_filter_candidates("Social") == ["Social", "social", "S", "s"]
    assert _report_filter_candidates("Governance") == [
        "Governance",
        "governance",
        "G",
        "g",
    ]


def test_report_filter_candidates_for_esg_do_not_filter():
    assert _report_filter_candidates("ESG") == [None]
