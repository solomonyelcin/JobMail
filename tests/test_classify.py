import pytest

from app.classify import classify, extract_company, extract_role, parse_sender


@pytest.mark.parametrize("subject,snippet,expected", [
    ("Thank you for applying to Acme", "", "applied"),
    ("Interview invitation", "we'd like to schedule", "interview"),
    ("Your coding challenge", "complete the HackerRank test", "assessment"),
    ("Offer letter from Acme", "We are pleased to offer you", "offer"),
    ("Update on your application", "Unfortunately we will not be moving forward", "rejected"),
    ("New jobs for you", "job alert", "opening"),
    ("Your order has shipped", "Track your package", None),
    ("Weekly newsletter", "Top 10 recipes", None),
])
def test_classify(subject, snippet, expected):
    assert classify(subject, snippet, "") == expected


def test_rejection_beats_thanks_for_applying():
    assert classify("Update", "Thank you for applying. Unfortunately we chose other candidates.", "") == "rejected"


def test_parse_sender():
    assert parse_sender('"Acme Careers" <Jobs@Acme.com>') == ("Acme Careers", "jobs@acme.com")
    assert parse_sender("plain@x.com") == ("", "plain@x.com")


@pytest.mark.parametrize("sender,subject,expected", [
    ("Acme Careers <jobs@acme.com>", "Hello", "Acme"),
    ("Globex Recruiting Team <no-reply@globex.io>", "x", "Globex"),
    ("Acme via Greenhouse <no-reply@greenhouse.io>", "x", "Acme"),
    ("jobs@initech.com", "Your application", "Initech"),
    ("LinkedIn <jobs@linkedin.com>", "Your application to Hooli", "Hooli"),
])
def test_extract_company(sender, subject, expected):
    assert extract_company(sender, subject) == expected


@pytest.mark.parametrize("subject,body,expected", [
    ("Application for Backend Engineer at Acme", "", "Backend Engineer"),
    ("Your application", "Thanks for applying for the Data Analyst position at Acme", "Data Analyst"),
    ("Hello", "nothing here", ""),
])
def test_extract_role(subject, body, expected):
    assert extract_role(subject, body) == expected
