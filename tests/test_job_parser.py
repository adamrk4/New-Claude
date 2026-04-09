"""Tests for the job parser module."""
from career_agent.parsers.job_parser import detect_experience_level, make_external_id, normalise_text, strip_html


class TestStripHtml:
    def test_strips_tags(self):
        assert strip_html("<p>Hello <b>world</b></p>") == "Hello world"

    def test_collapses_whitespace(self):
        result = strip_html("  <span>  foo   </span>  ")
        assert "  " not in result

    def test_plain_text_unchanged(self):
        assert strip_html("plain text") == "plain text"


class TestNormaliseText:
    def test_lowercases(self):
        assert normalise_text("SOLUTIONS ENGINEER") == "solutions engineer"

    def test_strips_html_and_lowercases(self):
        result = normalise_text("<b>PRE-SALES</b>")
        assert result == "pre-sales"


class TestDetectExperienceLevel:
    def test_detects_junior(self):
        assert detect_experience_level("Junior Solutions Engineer") == "entry"

    def test_detects_entry_level(self):
        assert detect_experience_level("Entry Level position") == "entry"

    def test_detects_0_2_years(self):
        assert detect_experience_level("0-2 years experience required") == "entry"

    def test_detects_new_grad(self):
        assert detect_experience_level("New Grad or Recent Graduate") == "entry"

    def test_detects_senior_as_mid(self):
        assert detect_experience_level("Senior Solutions Engineer") == "mid"

    def test_returns_none_for_unknown(self):
        assert detect_experience_level("Solutions Engineer, great opportunity") is None

    def test_detects_hebrew_no_experience(self):
        assert detect_experience_level("ללא ניסיון נדרש") == "entry"


class TestMakeExternalId:
    def test_stable_for_same_url(self):
        url = "https://example.com/jobs/123"
        assert make_external_id(url) == make_external_id(url)

    def test_different_for_different_urls(self):
        assert make_external_id("https://a.com/1") != make_external_id("https://a.com/2")

    def test_length_16(self):
        assert len(make_external_id("https://example.com")) == 16
