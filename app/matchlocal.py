"""Offline resume-vs-job-mail comparison (no AI needed).

Looks for known skills in the job mail and in your resume/profile, then reports what matches, what is
missing and what to emphasise. It is a keyword comparison, so it is a quick first read, not a verdict.
"""
import re

# canonical name -> regex alternatives (matched case-insensitively on word boundaries)
SKILLS = {
    "C#": [r"c#", r"c sharp", r"csharp"],
    ".NET": [r"\.net(?! ?framework)", r"dotnet", r"asp\.net", r"\.net core", r"\.net \d+"],
    ".NET Framework": [r"\.net framework"],
    "ASP.NET Core": [r"asp\.net core", r"aspnet core"],
    "Web API": [r"web ?api", r"rest(?:ful)? apis?", r"rest services?"],
    "Entity Framework": [r"entity framework", r"ef core", r"\bef\b"],
    "LINQ": [r"linq"],
    "Microservices": [r"micro-?services?"],
    "Angular": [r"angular(?:js)?"],
    "React": [r"react(?:\.js|js)?"],
    "TypeScript": [r"typescript"],
    "JavaScript": [r"javascript", r"\bjs\b", r"ecmascript"],
    "HTML/CSS": [r"html5?", r"css3?"],
    "SQL Server": [r"sql server", r"mssql", r"t-?sql"],
    "SQL": [r"\bsql\b"],
    "PostgreSQL": [r"postgres(?:ql)?"],
    "MySQL": [r"mysql"],
    "MongoDB": [r"mongo ?db"],
    "Snowflake": [r"snowflake"],
    "Elasticsearch": [r"elastic ?search", r"\belk\b"],
    "Redis": [r"redis"],
    "RabbitMQ": [r"rabbit ?mq"],
    "Kafka": [r"kafka"],
    "Azure": [r"azure"],
    "AWS": [r"\baws\b", r"amazon web services", r"\bec2\b", r"\bs3\b", r"lambda"],
    "GCP": [r"\bgcp\b", r"google cloud"],
    "Docker": [r"docker"],
    "Kubernetes": [r"kubernetes", r"\bk8s\b", r"\baks\b"],
    "CI/CD": [r"ci ?/ ?cd", r"continuous (?:integration|delivery|deployment)", r"azure devops", r"jenkins", r"github actions"],
    "Git": [r"\bgit\b", r"github", r"gitlab", r"bitbucket"],
    "Terraform": [r"terraform"],
    "Java": [r"\bjava\b(?!script)", r"spring boot", r"\bspring\b"],
    "Python": [r"python", r"django", r"flask", r"fastapi"],
    "Node.js": [r"node(?:\.js|js)?\b"],
    "Go": [r"\bgolang\b", r"\bgo (?:developer|engineer|lang)"],
    "gRPC": [r"grpc"],
    "GraphQL": [r"graphql"],
    "MuleSoft": [r"mulesoft", r"mule ?soft"],
    "SharePoint": [r"sharepoint"],
    "Kendo UI": [r"kendo"],
    "ag-Grid": [r"ag-?grid"],
    "Multithreading": [r"multi-?thread(?:ing|ed)?", r"concurrency", r"async(?:hronous)? programming", r"tpl\b"],
    "Design Patterns": [r"design patterns?", r"\bsolid\b", r"\bddd\b", r"domain[- ]driven", r"clean architecture"],
    "Unit Testing": [r"unit test(?:ing|s)?", r"\btdd\b", r"xunit", r"nunit", r"\bmoq\b", r"mstest"],
    "Agile/Scrum": [r"agile", r"scrum", r"kanban"],
    "System Design": [r"system design", r"architecture", r"scalab(?:le|ility)", r"high[- ]availability"],
    "Leadership": [r"team lead", r"tech lead", r"lead(?:ing)? a team", r"mentor(?:ing)?", r"people management", r"engineering manager"],
    "Power BI / Analytics": [r"power ?bi", r"tableau", r"data visuali[sz]ation"],
    "AI / LLM": [r"\bllm\b", r"generative ai", r"\bgenai\b", r"machine learning", r"\bml\b", r"copilot", r"openai"],
    "Security": [r"oauth", r"\bjwt\b", r"identity server", r"owasp", r"authentication"],
    "WCF/SOAP": [r"\bwcf\b", r"\bsoap\b"],
    "Windows Services": [r"windows services?", r"\bwpf\b", r"winforms"],
}
_COMPILED = {name: re.compile(r"(?<![\w.#+])(?:" + "|".join(alts) + r")(?![\w#+])", re.I) for name, alts in SKILLS.items()}
# a generic word such as "architecture" should not count as a hard requirement on its own
SOFT = {"System Design", "Leadership", "Agile/Scrum", "Security", "Git", "HTML/CSS", "Design Patterns"}
EXP_RE = re.compile(r"(?i)(\d{1,2})\s*(?:\+|-|to|–)?\s*(\d{1,2})?\s*\+?\s*(?:years?|yrs?)")
TOTAL_EXP_RE = re.compile(r"(?i)(\d{1,2})\s*\+?\s*(?:years?|yrs?)")


def skills_in(text):
    return {name for name, rx in _COMPILED.items() if rx.search(text or "")}


def years_required(text):
    """Highest 'N years' figure that sits next to an experience word, or None."""
    best = None
    for m in re.finditer(r"(?i)(\d{1,2})\s*\+?\s*(?:-|to|–)?\s*(\d{1,2})?\s*\+?\s*(?:years?|yrs?)[^.\n]{0,40}?(?:experience|exp)", text or ""):
        n = int(m.group(1))
        if 0 < n <= 30:
            best = n if best is None else min(best, n)  # "5-8 years" -> the lower bound is the real minimum
    return best


def years_claimed(resume_text):
    """Years of experience the resume claims ("9+ years"), or None."""
    vals = [int(m.group(1)) for m in TOTAL_EXP_RE.finditer((resume_text or "")[:2500]) if 0 < int(m.group(1)) <= 40]
    return max(vals) if vals else None


def compare(email, resume_text):
    """Return {score, matched, missing, extra, soft_missing, years_required, years_have, verdict, notes}."""
    mail_text = "\n".join([email.get("subject") or "", email.get("body_text") or email.get("snippet") or ""])
    wanted, have = skills_in(mail_text), skills_in(resume_text)
    hard = {s for s in wanted if s not in SOFT}
    soft = wanted & SOFT
    matched = sorted(wanted & have)
    missing = sorted(hard - have)
    soft_missing = sorted(soft - have)
    # ".NET Framework" in the mail is covered by ".NET" on the resume, and so on
    if ".NET Framework" in missing and ".NET" in have:
        missing.remove(".NET Framework")
        matched.append(".NET Framework")
    if "SQL" in missing and ({"SQL Server", "PostgreSQL", "MySQL", "Snowflake"} & have):
        missing.remove("SQL")
        matched.append("SQL")
    matched = sorted(set(matched))
    extra = sorted((have - wanted) & {"C#", ".NET", "Angular", "Azure", "Docker", "Kubernetes", "Microservices",
                                      "Snowflake", "RabbitMQ", "Elasticsearch", "AWS", "Kafka", "React", "Python", "Java"})
    need, got = years_required(mail_text), years_claimed(resume_text)
    notes = []
    if need and got:
        notes.append(f"They ask for about {need}+ years; your resume says {got}+." if got >= need
                     else f"They ask for about {need}+ years; your resume says {got}+, which is short.")
    elif need:
        notes.append(f"They ask for about {need}+ years of experience.")
    if not wanted:
        score, verdict = None, "No recognisable skills in this email, so there is nothing to compare."
    else:
        score = round(100 * len(matched) / max(1, len(wanted - SOFT) + len(soft)))
        if need and got and got < need - 1:
            score = max(0, score - 15)
        verdict = ("Strong match on the stated skills." if score >= 75 else
                   "Decent match, with some gaps to address." if score >= 50 else
                   "Weak match on the stated skills.")
    return {"score": score, "matched": matched, "missing": missing, "soft_missing": soft_missing,
            "extra": extra, "years_required": need, "years_have": got, "verdict": verdict, "notes": notes,
            "wanted": sorted(wanted)}
