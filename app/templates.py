"""Ready-made reply and application messages, filled in from the email and your profile.

These work without AI. Anything unknown is left as a [bracketed placeholder] so it is obvious what to fill in
before sending. SmartMail only ever creates Gmail drafts, so you always review the text first.
"""
import re

# id -> (label, categories it suits, attach resume by default, new thread instead of reply)
TEMPLATES = {
    "apply": ("Apply by email", ("opening", "recruiter"), True, True),
    "interested": ("I'm interested, share details", ("opening", "recruiter"), True, False),
    "share_details": ("Share my notice period, CTC and location", ("recruiter", "opening", "applied"), True, False),
    "more_info": ("Ask for the JD and process", ("recruiter", "opening"), False, False),
    "confirm_slot": ("Confirm the interview slot", ("interview", "assessment"), False, False),
    "availability": ("Share my availability", ("interview", "assessment"), False, False),
    "reschedule": ("Ask to reschedule", ("interview", "assessment"), False, False),
    "extension": ("Ask for more time on the assessment", ("assessment",), False, False),
    "thank_you": ("Thank you after the interview", ("interview",), False, False),
    "followup": ("Follow up on my application", ("applied", "interview", "assessment", "opening"), True, False),
    "accept_offer": ("Accept the offer", ("offer",), False, False),
    "offer_time": ("Ask for time to decide", ("offer",), False, False),
    "negotiate": ("Discuss the offer terms", ("offer",), False, False),
    "decline": ("Politely decline", ("recruiter", "opening", "offer", "interview"), False, False),
    "ack_rejection": ("Thank them and stay in touch", ("rejected",), False, False),
}
ORDER = list(TEMPLATES)


def first_name(sender):
    """'Priya Sharma <p@x.com>' -> 'Priya'. Returns '' for team or no-reply senders."""
    name = re.sub(r"<[^>]*>", "", sender or "").replace('"', "").strip()
    if not name or "@" in name:
        return ""
    low = name.lower()
    if re.search(r"(?i)(team|careers|recruit|hr\b|talent|jobs|hiring|no-?reply|notifications?|support|alerts?)", low):
        return ""
    word = name.split()[0]
    return word.capitalize() if word.isalpha() else ""


def catalog(category):
    """All templates, the ones that suit this email category first."""
    items = [{"id": t, "label": TEMPLATES[t][0], "attach": TEMPLATES[t][2], "new_thread": TEMPLATES[t][3],
              "suggested": category in TEMPLATES[t][1]} for t in ORDER]
    return sorted(items, key=lambda i: not i["suggested"])


def _ph(value, label):
    value = (value or "").strip()
    return value if value else f"[{label}]"


def render(template_id, email, application, profile, matched_skills=None):
    """Return {"subject", "body", "attach", "new_thread"} or None for an unknown template."""
    if template_id not in TEMPLATES:
        return None
    label, _cats, attach, new_thread = TEMPLATES[template_id]
    p = profile or {}
    app = application or {}
    company = (email.get("company") or app.get("company") or "").strip()
    role = (email.get("role") or app.get("role") or "").strip()
    name = _ph(p.get("full_name"), "Your name")
    hi = first_name(email.get("sender"))
    greet = f"Hi {hi}," if hi else "Hello,"
    role_txt = role or "[role]"
    at_company = f" at {company}" if company else ""
    sign = f"Thanks and regards,\n{name}"
    contact_bits = [b for b in (p.get("phone"), p.get("email_contact"), p.get("linkedin")) if b]
    contact = ("\n" + " | ".join(contact_bits)) if contact_bits else ""
    skills = ", ".join((matched_skills or [])[:6])
    subj = (email.get("subject") or "").strip()

    def info_block():
        return "\n".join([
            f"- Total experience: {_ph(p.get('experience'), 'years of experience')}",
            f"- Current location: {_ph(p.get('location'), 'current location')}",
            f"- Notice period: {_ph(p.get('notice_period'), 'notice period')}",
            f"- Current CTC: {_ph(p.get('current_ctc'), 'current CTC')}",
            f"- Expected CTC: {_ph(p.get('expected_ctc'), 'expected CTC')}",
        ])

    resume_line = "I have attached my resume for your reference." if attach else ""

    if template_id == "apply":
        pitch = (f"My background includes {skills}, which lines up with what you are looking for."
                 if skills else "My background lines up well with the requirements, and I would be glad to go into detail.")
        subject = f"Application for {role_txt}{at_company} - {name}"
        body = (f"Hello,\n\nI would like to apply for the {role_txt} position{at_company}. {pitch}\n\n"
                f"{info_block()}\n\n{resume_line} Please let me know if you need anything else from my side.\n\n{sign}{contact}")
    elif template_id == "interested":
        subject = "Re: " + subj if subj else f"Interested in the {role_txt} role"
        body = (f"{greet}\n\nThank you for reaching out. I am interested in the {role_txt} opportunity{at_company} "
                f"and would like to learn more.\n\n{info_block()}\n\n{resume_line} Happy to connect whenever suits you.\n\n{sign}{contact}")
    elif template_id == "share_details":
        subject = "Re: " + subj if subj else "My details"
        body = f"{greet}\n\nThanks for your message. Here are the details you asked for:\n\n{info_block()}\n\n{resume_line}\n\n{sign}{contact}"
    elif template_id == "more_info":
        subject = "Re: " + subj if subj else f"Questions about the {role_txt} role"
        body = (f"{greet}\n\nThank you for reaching out about the {role_txt} role{at_company}. Before we go further, could you share:\n\n"
                "1. The full job description and the main responsibilities\n2. The work location and work mode (remote, hybrid or on-site)\n"
                "3. The team, and the interview process and timeline\n4. The compensation range for the role\n\n"
                f"This will help me respond properly.\n\n{sign}")
    elif template_id == "confirm_slot":
        subject = "Re: " + subj
        body = (f"{greet}\n\nThank you for the invitation. I confirm my availability for the interview "
                f"on [date and time, with time zone]. Please share the meeting link or venue and the names of the panel if possible.\n\n{sign}")
    elif template_id == "availability":
        subject = "Re: " + subj
        body = (f"{greet}\n\nThank you for the invitation. I am available at these times:\n\n- [date, time and time zone]\n- [date, time and time zone]\n- [date, time and time zone]\n\n"
                f"Please pick whichever works best for you.\n\n{sign}")
    elif template_id == "reschedule":
        subject = "Re: " + subj
        body = (f"{greet}\n\nThank you for scheduling this. Unfortunately I am not able to make the proposed time because [reason]. "
                f"Could we move it to [new date and time], or any slot that suits you in the next few days? Sorry for the inconvenience.\n\n{sign}")
    elif template_id == "extension":
        subject = "Re: " + subj
        body = (f"{greet}\n\nThank you for sharing the assessment. Because of [reason], I would like to request an extension until [date] to give it proper attention. "
                f"Please let me know if that is possible.\n\n{sign}")
    elif template_id == "thank_you":
        subject = "Thank you - " + (role_txt if role else subj or "interview")
        body = (f"{greet}\n\nThank you for taking the time to speak with me about the {role_txt} role{at_company}. "
                f"I enjoyed learning about [something specific from the conversation], and I remain very interested. "
                f"Please let me know if you need anything further from me.\n\n{sign}")
    elif template_id == "followup":
        subject = f"Following up: {role_txt} application" if role else "Re: " + subj
        body = (f"{greet}\n\nI wanted to follow up on my application for the {role_txt} position{at_company}. "
                f"I remain very interested and would be glad to share anything else you need. Could you let me know where things stand?\n\n"
                f"{resume_line}\n\n{sign}")
    elif template_id == "accept_offer":
        subject = "Re: " + subj
        body = (f"{greet}\n\nThank you for the offer for the {role_txt} position{at_company}. I am pleased to accept it. "
                f"My proposed joining date is [date]. Please send the next steps and the documents I need to provide.\n\n{sign}")
    elif template_id == "offer_time":
        subject = "Re: " + subj
        body = (f"{greet}\n\nThank you very much for the offer for the {role_txt} position{at_company}. I am excited about it. "
                f"Could I have until [date] to review the details and give you my decision?\n\n{sign}")
    elif template_id == "negotiate":
        subject = "Re: " + subj
        body = (f"{greet}\n\nThank you for the offer for the {role_txt} position{at_company}. I am keen to join. "
                f"Before I confirm, I would like to discuss [compensation / joining date / role level]. "
                f"Based on my experience, I was hoping for [your expectation]. Could we find a time to talk?\n\n{sign}")
    elif template_id == "decline":
        subject = "Re: " + subj
        body = (f"{greet}\n\nThank you for thinking of me for the {role_txt} role{at_company}. After careful thought, I have decided not to take this forward "
                f"at this time. I appreciate your time, and I would be happy to stay in touch for future opportunities.\n\n{sign}")
    else:  # ack_rejection
        subject = "Re: " + subj
        body = (f"{greet}\n\nThank you for letting me know, and for the time you spent on my application. "
                f"I would appreciate any feedback you can share, and I would be glad to be considered for future roles that fit my background.\n\n{sign}")
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    body = re.sub(r" {2,}", " ", body)
    return {"subject": subject.strip(), "body": body, "attach": attach, "new_thread": new_thread}
