from admin_logic import fmt_local, format_breakdown, format_results, parse_coords, parse_count


def test_parse_coords_variants():
    assert parse_coords("55.75 37.61") == (55.75, 37.61)
    assert parse_coords("55.75, 37.61") == (55.75, 37.61)
    assert parse_coords("55,75 37,61") == (55.75, 37.61)
    assert parse_coords("  55.75;37.61 ") == (55.75, 37.61)


def test_parse_coords_invalid():
    assert parse_coords("abc") is None
    assert parse_coords("55.75") is None
    assert parse_coords("91 10") is None
    assert parse_coords("10 181") is None


def test_parse_count():
    assert parse_count("5") == 5
    assert parse_count(" 50 ") == 50
    assert parse_count("0") is None
    assert parse_count("51") is None
    assert parse_count("x") is None


def test_fmt_local_converts_tz():
    assert fmt_local("2026-08-01T10:30:00+00:00", "Europe/Sofia") == "13:30"
    assert fmt_local("2026-08-01T10:30:00", "UTC") == "10:30"
    assert fmt_local(None, "UTC") == "—"


def _row(name, start, finish, taken):
    return {"name": name, "started_at": start, "finished_at": finish,
            "taken_count": taken, "last_taken_at": finish}


def test_format_results_escapes_ranks_and_converts():
    rows = [
        _row("Б", "2026-08-01T10:00:00+00:00", "2026-08-01T11:30:00+00:00", 3),
        _row("<b>A</b>", "2026-08-01T10:00:00+00:00", "2026-08-01T10:45:05+00:00", 3),
    ]
    out = format_results(rows, "Europe/Sofia")
    assert len(out) == 1
    text = out[0]
    assert text.startswith("<pre>") and text.endswith("</pre>")
    assert "&lt;b&gt;A&lt;/b&gt;" in text
    assert text.index("&lt;b&gt;") < text.index("Б")  # faster first
    assert "0:45:05" in text and "13:00" in text


def test_format_results_splits_long_output():
    rows = [_row(f"К{i}", "2026-08-01T10:00:00+00:00", None, 1) for i in range(120)]
    out = format_results(rows, "UTC", limit=500)
    assert len(out) > 1
    assert all(len(m) < 4096 and m.startswith("<pre>") for m in out)
    assert sum(m.count("\n") - 0 for m in out) >= 120


def test_format_results_empty():
    assert format_results([], "UTC") == ["Пока нет команд."]


def test_format_breakdown_lists_points_with_local_times():
    slow = {**_row("Б", "2026-08-01T10:00:00+00:00", "2026-08-01T11:30:00+00:00", 2),
            "taken": [{"label": "Мост", "taken_at": "2026-08-01T10:20:00+00:00"},
                      {"label": "<Парк>", "taken_at": "2026-08-01T11:30:00+00:00"}]}
    fast = {**_row("<A>", "2026-08-01T10:00:00+00:00", "2026-08-01T10:45:00+00:00", 1),
            "taken": [{"label": None, "taken_at": "2026-08-01T10:45:00+00:00"}]}
    idle = {**_row("В", None, None, 0), "taken": []}
    out = format_breakdown([slow, idle, fast], "Europe/Sofia")
    assert len(out) == 1
    text = out[0]
    assert "<b>Б</b>: 1) Мост 13:20, 2) &lt;Парк&gt; 14:30" in text
    assert "<b>&lt;A&gt;</b>: 1) без названия 13:45" in text
    assert "<b>В</b>: —" in text
    assert text.index("<b>&lt;A&gt;</b>") < text.index("<b>Б</b>") < text.index("<b>В</b>")  # ranked


def test_format_breakdown_splits_long_output():
    taken = [{"label": f"Точка {i}", "taken_at": "2026-08-01T10:00:00+00:00"} for i in range(40)]
    rows = [{**_row(f"К{i}", "2026-08-01T10:00:00+00:00", None, 40), "taken": taken} for i in range(30)]
    out = format_breakdown(rows, "UTC", limit=500)
    assert len(out) > 1
    assert all(len(m) <= 500 for m in out)
    joined = " ".join(out)
    assert joined.count("40) Точка 39") == 30


def test_format_breakdown_empty():
    assert format_breakdown([], "UTC") == []
