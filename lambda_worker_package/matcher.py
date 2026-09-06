from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from skills import skills
from ai_extractor import analyze_job
from resume_extractor import analyze_resume


# --------------------------------------------------
# Job requirement strength multipliers
# --------------------------------------------------

STRENGTH_MULTIPLIERS = {
    "HARD_REQUIREMENT": 3.0,
    "STRONG_REQUIREMENT": 2.5,
    "FAMILIARITY": 1.5,
    "EXAMPLE": 0.75,
    "PREFERRED": 1.5,
    "MENTIONED": 1.0
}


# --------------------------------------------------
# Resume evidence multipliers
# --------------------------------------------------

RESUME_EVIDENCE_MULTIPLIERS = {
    "PROFESSIONAL": 1.0,
    "PROJECT": 1.0,
    "EDUCATION": 0.65,
    "SKILLS_SECTION": 0.40
}


MAX_TRANSFERABLE_CREDIT = 0.30


# --------------------------------------------------
# Convert resume date text into datetime
# --------------------------------------------------

def parse_resume_date(date_text):

    cleaned_date = date_text.strip()

    if cleaned_date.lower() in [
        "present",
        "current"
    ]:
        return datetime.now()

    possible_formats = [
        "%b %Y",
        "%B %Y"
    ]

    for date_format in possible_formats:

        try:
            return datetime.strptime(
                cleaned_date,
                date_format
            )

        except ValueError:
            continue

    return None


# --------------------------------------------------
# Main reusable matcher
# --------------------------------------------------

def match_job(
    resume_text,
    job_text,
    resume_analysis=None
):

    # --------------------------------------------------
    # AI analysis
    # --------------------------------------------------

    print()

    if resume_analysis is None:

        print(
            "Analyzing job and resume with AI..."
        )

        with ThreadPoolExecutor(
            max_workers=2
        ) as executor:

            job_future = executor.submit(
                analyze_job,
                job_text
            )

            resume_future = executor.submit(
                analyze_resume,
                resume_text
            )

            job_analysis = (
                job_future.result()
            )

            resume_analysis = (
                resume_future.result()
            )

    else:

        print(
            "Using cached resume analysis."
        )

        print(
            "Analyzing job with AI..."
        )

        job_analysis = analyze_job(
            job_text
        )


    # --------------------------------------------------
    # Build resume skill lookup
    # --------------------------------------------------

    resume_skill_data = {}

    for item in resume_analysis.skills:

        resume_skill_data[item.skill] = {
            "evidence_type": item.evidence_type,
            "demonstrated": item.demonstrated,
            "evidence": item.evidence,
            "context": item.context
        }


    # --------------------------------------------------
    # Build job skill lookup
    # --------------------------------------------------

    job_skill_data = {}

    def add_job_skill(item):

        if item.skill not in skills:
            return

        if item.strength not in STRENGTH_MULTIPLIERS:
            return

        job_skill_data[item.skill] = {
            "strength": item.strength,
            "reason": item.reason,
            "evidence": item.evidence
        }


    for item in job_analysis.required_skills:
        add_job_skill(item)

    for item in job_analysis.preferred_skills:
        add_job_skill(item)

    for item in job_analysis.mentioned_skills:
        add_job_skill(item)


    # --------------------------------------------------
    # Result storage
    # --------------------------------------------------

    matched_skills = []
    partial_skills = []
    missing_skills = []

    total_points = 0
    earned_points = 0


    # --------------------------------------------------
    # Category storage
    # --------------------------------------------------

    category_totals = {}
    category_matches = {}


    # --------------------------------------------------
    # Family storage
    # --------------------------------------------------

    family_totals = {}
    family_matches = {}


    # --------------------------------------------------
    # Analyze each job skill
    # --------------------------------------------------

    for skill, job_info in job_skill_data.items():

        skill_info = skills[skill]

        base_weight = skill_info["weight"]
        category = skill_info["category"]
        family = skill_info["family"]
        strength = job_info["strength"]

        strength_multiplier = (
            STRENGTH_MULTIPLIERS[
                strength
            ]
        )

        max_skill_points = (
            base_weight
            * strength_multiplier
        )

        total_points += max_skill_points


        # --------------------------------------------------
        # Initialize category
        # --------------------------------------------------

        if category not in category_totals:

            category_totals[category] = 0
            category_matches[category] = 0


        # --------------------------------------------------
        # Initialize family
        # --------------------------------------------------

        if family not in family_totals:

            family_totals[family] = 0
            family_matches[family] = 0


        category_totals[
            category
        ] += max_skill_points

        family_totals[
            family
        ] += max_skill_points


        # --------------------------------------------------
        # Skill missing entirely
        # --------------------------------------------------

        if skill not in resume_skill_data:

            missing_skills.append(
                {
                    "skill": skill,
                    "strength": strength,
                    "max_points": max_skill_points,
                    "reason": job_info["reason"],
                    "job_evidence": job_info["evidence"],
                    "category": category,
                    "family": family
                }
            )

            continue


        # --------------------------------------------------
        # Resume contains skill
        # --------------------------------------------------

        resume_info = resume_skill_data[
            skill
        ]

        evidence_type = resume_info[
            "evidence_type"
        ]

        demonstrated = resume_info[
            "demonstrated"
        ]

        resume_multiplier = (
            RESUME_EVIDENCE_MULTIPLIERS.get(
                evidence_type,
                0
            )
        )

        earned_skill_points = (
            max_skill_points
            * resume_multiplier
        )

        earned_points += earned_skill_points

        category_matches[
            category
        ] += earned_skill_points

        family_matches[
            family
        ] += earned_skill_points


        result = {
            "skill": skill,
            "strength": strength,
            "max_points": max_skill_points,
            "earned_points": earned_skill_points,

            "evidence_type": evidence_type,
            "demonstrated": demonstrated,

            "resume_context": resume_info[
                "context"
            ],

            "resume_evidence": resume_info[
                "evidence"
            ],

            "job_reason": job_info[
                "reason"
            ],

            "job_evidence": job_info[
                "evidence"
            ],

            "category": category,
            "family": family
        }


        # --------------------------------------------------
        # Full evidence
        # --------------------------------------------------

        if resume_multiplier == 1.0:

            matched_skills.append(
                result
            )


        # --------------------------------------------------
        # Partial evidence
        # --------------------------------------------------

        else:

            partial_skills.append(
                result
            )


    # --------------------------------------------------
    # Technical score
    # --------------------------------------------------

    if total_points == 0:

        technical_match = 0

    else:

        technical_match = (
            earned_points
            / total_points
        ) * 100


    # --------------------------------------------------
    # Family transferable credit
    # --------------------------------------------------

    transferable_credit_points = 0

    for item in missing_skills:

        family = item[
            "family"
        ]

        family_total = family_totals[
            family
        ]

        family_matched = family_matches[
            family
        ]

        if family_total == 0:

            family_coverage = 0

        else:

            family_coverage = (
                family_matched
                / family_total
            )

        transferable_credit = (
            item["max_points"]
            * MAX_TRANSFERABLE_CREDIT
            * family_coverage
        )

        item[
            "transferable_credit"
        ] = transferable_credit

        transferable_credit_points += (
            transferable_credit
        )


    # --------------------------------------------------
    # Adjusted score
    # --------------------------------------------------

    adjusted_points = (
        earned_points
        + transferable_credit_points
    )

    if total_points == 0:

        adjusted_match = 0

    else:

        adjusted_match = (
            adjusted_points
            / total_points
        ) * 100


    # --------------------------------------------------
    # Technical recommendation
    # --------------------------------------------------

    if adjusted_match >= 80:

        technical_recommendation = (
            "STRONG TECHNICAL MATCH"
        )

    elif adjusted_match >= 60:

        technical_recommendation = (
            "POSSIBLE TECHNICAL MATCH"
        )

    else:

        technical_recommendation = (
            "WEAK TECHNICAL MATCH"
        )


    # --------------------------------------------------
    # Relevant professional experience
    # --------------------------------------------------

    relevant_roles = [
        role
        for role in resume_analysis.professional_experience
        if role.relevant_to_cloud_devops
    ]

    total_relevant_months = 0

    role_experience_results = []


    for role in relevant_roles:

        start_date = parse_resume_date(
            role.start_date
        )

        end_date = parse_resume_date(
            role.end_date
        )

        if (
            start_date is None
            or end_date is None
        ):

            role_experience_results.append(
                {
                    "role": role,
                    "months": None
                }
            )

            continue


        months = (
            (end_date.year - start_date.year) * 12
            + (end_date.month - start_date.month)
        )

        months += 1

        months = max(
            months,
            0
        )

        total_relevant_months += months

        role_experience_results.append(
            {
                "role": role,
                "months": months
            }
        )


    # --------------------------------------------------
    # Convert experience to years
    # --------------------------------------------------

    professional_experience_years = (
        total_relevant_months
        / 12
    )

    required_years = (
        job_analysis.required_years
    )


    # --------------------------------------------------
    # Experience match
    # --------------------------------------------------

    if required_years == 0:

        experience_match = 100

    else:

        experience_match = (
            professional_experience_years
            / required_years
        ) * 100

        experience_match = min(
            experience_match,
            100
        )


    # --------------------------------------------------
    # Missing requirement groups
    # --------------------------------------------------

    hard_missing_skills = [
        item
        for item in missing_skills
        if item["strength"]
        == "HARD_REQUIREMENT"
    ]

    strong_missing_skills = [
        item
        for item in missing_skills
        if item["strength"]
        == "STRONG_REQUIREMENT"
    ]


    # --------------------------------------------------
    # Relevant projects
    # --------------------------------------------------

    relevant_projects = [
        project
        for project in resume_analysis.projects
        if project.relevant_to_cloud_devops
    ]

    has_relevant_project = (
        len(relevant_projects) > 0
    )


    # --------------------------------------------------
    # Experience gap
    # --------------------------------------------------

    experience_gap = max(
        required_years
        - professional_experience_years,
        0
    )


    # --------------------------------------------------
    # Decision engine
    # --------------------------------------------------

    decision_reasons = []


    # --------------------------------------------------
    # SKIP
    # --------------------------------------------------

    if (
        adjusted_match < 50
        and len(hard_missing_skills) >= 1
        and experience_gap >= 2
    ):

        final_recommendation = "SKIP"

        decision_reasons.append(
            "Technical match is below 50%."
        )

        decision_reasons.append(
            "At least one hard technical requirement is missing."
        )

        decision_reasons.append(
            "Professional experience is at least 2 years below the job requirement."
        )


    # --------------------------------------------------
    # APPLY
    # --------------------------------------------------

    elif (
        adjusted_match >= 75
        and len(hard_missing_skills) == 0
        and experience_match >= 75
    ):

        final_recommendation = "APPLY"

        decision_reasons.append(
            "Technical match is strong."
        )

        decision_reasons.append(
            "No hard technical requirements are missing."
        )

        decision_reasons.append(
            "Professional experience is close to or meets the requirement."
        )


    # --------------------------------------------------
    # APPLY - entry level
    # --------------------------------------------------

    elif (
        required_years == 0
        and adjusted_match >= 65
        and len(hard_missing_skills) == 0
    ):

        final_recommendation = "APPLY"

        decision_reasons.append(
            "The role does not require prior professional experience."
        )

        decision_reasons.append(
            "Technical match is strong enough for an entry-level application."
        )

        if has_relevant_project:

            decision_reasons.append(
                "The resume demonstrates relevant Cloud/DevOps project experience."
            )


    # --------------------------------------------------
    # STRETCH
    # --------------------------------------------------

    else:

        final_recommendation = "STRETCH"

        if adjusted_match < 60:

            decision_reasons.append(
                "Technical match is below 60%."
            )

        else:

            decision_reasons.append(
                "Technical match is reasonably competitive."
            )

        if len(hard_missing_skills) > 0:

            decision_reasons.append(
                "One or more hard technical requirements are missing."
            )

        if experience_gap > 0:

            decision_reasons.append(
                "Professional experience is below the stated requirement."
            )

        if has_relevant_project:

            decision_reasons.append(
                "Relevant Cloud/DevOps project experience strengthens the application."
            )


    # --------------------------------------------------
    # Print job analysis
    # --------------------------------------------------

    print()
    print("=" * 60)
    print("JOB ANALYSIS")
    print("=" * 60)

    print(
        "Job title:",
        job_analysis.job_title
    )

    print(
        "Required experience:",
        required_years,
        "years"
    )


    # --------------------------------------------------
    # Demonstrated matches
    # --------------------------------------------------

    print()
    print("=" * 60)
    print("DEMONSTRATED SKILL MATCHES")
    print("=" * 60)

    if len(matched_skills) == 0:

        print(
            "No demonstrated matches."
        )

    for item in matched_skills:

        print()

        print(
            "[+]",
            item["skill"],
            "-",
            item["strength"]
        )

        print(
            "Resume evidence:",
            item["evidence_type"]
        )

        print(
            "Points:",
            round(
                item["earned_points"],
                2
            ),
            "/",
            round(
                item["max_points"],
                2
            )
        )

        print(
            "Context:",
            item["resume_context"]
        )


    # --------------------------------------------------
    # Partial matches
    # --------------------------------------------------

    print()
    print("=" * 60)
    print("PARTIAL RESUME MATCHES")
    print("=" * 60)

    if len(partial_skills) == 0:

        print(
            "No partial resume matches."
        )

    for item in partial_skills:

        print()

        print(
            "[~]",
            item["skill"],
            "-",
            item["strength"]
        )

        print(
            "Resume evidence:",
            item["evidence_type"]
        )

        print(
            "Demonstrated:",
            item["demonstrated"]
        )

        print(
            "Points:",
            round(
                item["earned_points"],
                2
            ),
            "/",
            round(
                item["max_points"],
                2
            )
        )

        print(
            "Context:",
            item["resume_context"]
        )


    # --------------------------------------------------
    # Missing skills
    # --------------------------------------------------

    print()
    print("=" * 60)
    print("MISSING SKILLS")
    print("=" * 60)

    for item in missing_skills:

        print()

        print(
            "[-]",
            item["skill"],
            "-",
            item["strength"]
        )

        print(
            "Possible points:",
            round(
                item["max_points"],
                2
            )
        )


    # --------------------------------------------------
    # Category scores
    # --------------------------------------------------

    print()
    print("=" * 60)
    print("CATEGORY SCORES")
    print("=" * 60)

    category_scores = {}

    for category in category_totals:

        total = category_totals[
            category
        ]

        matched = category_matches[
            category
        ]

        percentage = (
            matched
            / total
        ) * 100

        category_scores[
            category
        ] = round(
            percentage,
            2
        )

        print(
            category,
            "-",
            round(
                percentage,
                2
            ),
            "%"
        )


    # --------------------------------------------------
    # Family scores
    # --------------------------------------------------

    print()
    print("=" * 60)
    print("FAMILY SCORES")
    print("=" * 60)

    family_scores = {}

    for family in family_totals:

        total = family_totals[
            family
        ]

        matched = family_matches[
            family
        ]

        percentage = (
            matched
            / total
        ) * 100

        family_scores[
            family
        ] = round(
            percentage,
            2
        )

        print(
            family,
            "-",
            round(
                percentage,
                2
            ),
            "%"
        )


    # --------------------------------------------------
    # Transferable credit
    # --------------------------------------------------

    print()
    print("=" * 60)
    print("TRANSFERABLE CREDIT")
    print("=" * 60)

    found_transferable = False

    for item in missing_skills:

        credit = item[
            "transferable_credit"
        ]

        if credit > 0:

            found_transferable = True

            print(
                "[~]",
                item["skill"],
                "-",
                round(
                    credit,
                    2
                ),
                "points from",
                item["family"],
                "experience"
            )

    if not found_transferable:

        print(
            "No transferable credit."
        )


    # --------------------------------------------------
    # Technical result
    # --------------------------------------------------

    print()
    print("=" * 60)
    print("TECHNICAL RESULT")
    print("=" * 60)

    print(
        "Resume evidence score:",
        round(
            technical_match,
            2
        ),
        "%"
    )

    print(
        "Transferable credit:",
        round(
            transferable_credit_points,
            2
        ),
        "points"
    )

    print(
        "Adjusted technical match:",
        round(
            adjusted_match,
            2
        ),
        "%"
    )

    print(
        "Technical recommendation:",
        technical_recommendation
    )


    # --------------------------------------------------
    # Professional experience result
    # --------------------------------------------------

    print()
    print("=" * 60)
    print("PROFESSIONAL EXPERIENCE RESULT")
    print("=" * 60)

    print(
        "Required experience:",
        required_years,
        "years"
    )

    print(
        "Relevant professional experience:",
        round(
            professional_experience_years,
            2
        ),
        "years"
    )

    print(
        "Experience match:",
        round(
            experience_match,
            2
        ),
        "%"
    )

    print()
    print("Relevant professional roles:")

    if len(role_experience_results) == 0:

        print(
            "No relevant professional Cloud/DevOps roles found."
        )

    for role_result in role_experience_results:

        role = role_result[
            "role"
        ]

        months = role_result[
            "months"
        ]

        print()

        print(
            "-",
            role.job_title,
            "at",
            role.company
        )

        print(
            "  Dates:",
            role.start_date,
            "-",
            role.end_date
        )

        if months is None:

            print(
                "  Duration: Could not parse dates"
            )

        else:

            print(
                "  Duration:",
                months,
                "months"
            )


    # --------------------------------------------------
    # Relevant projects
    # --------------------------------------------------

    print()
    print("=" * 60)
    print("RELEVANT PROJECT EXPERIENCE")
    print("=" * 60)

    if len(relevant_projects) == 0:

        print(
            "No relevant Cloud/DevOps projects found."
        )

    for project in relevant_projects:

        print()

        print(
            "Project:",
            project.project_name
        )

        print(
            "Skills:",
            ", ".join(
                project.demonstrated_skills
            )
        )

        print(
            "Reason:",
            project.relevance_reason
        )


    # --------------------------------------------------
    # Major gaps
    # --------------------------------------------------

    print()
    print("=" * 60)
    print("MAJOR TECHNICAL GAPS")
    print("=" * 60)

    major_gap_found = False

    for item in missing_skills:

        if item["strength"] in [
            "HARD_REQUIREMENT",
            "STRONG_REQUIREMENT"
        ]:

            major_gap_found = True

            print()

            print(
                item["skill"].upper()
            )

            print(
                "Strength:",
                item["strength"]
            )

            print(
                "Reason:",
                item["reason"]
            )

            print(
                "Evidence:",
                item["job_evidence"]
            )

    if not major_gap_found:

        print(
            "No major technical gaps."
        )


    # --------------------------------------------------
    # Smaller gaps
    # --------------------------------------------------

    print()
    print("=" * 60)
    print("SMALLER TECHNICAL GAPS")
    print("=" * 60)

    smaller_gap_found = False

    for item in missing_skills:

        if item["strength"] in [
            "FAMILIARITY",
            "EXAMPLE",
            "PREFERRED",
            "MENTIONED"
        ]:

            smaller_gap_found = True

            print()

            print(
                item["skill"].upper()
            )

            print(
                "Strength:",
                item["strength"]
            )

            print(
                "Reason:",
                item["reason"]
            )

    if not smaller_gap_found:

        print(
            "No smaller technical gaps."
        )


    # --------------------------------------------------
    # Other requirements
    # --------------------------------------------------

    print()
    print("=" * 60)
    print("OTHER JOB REQUIREMENTS")
    print("=" * 60)

    for requirement in job_analysis.other_requirements:

        print(
            "-",
            requirement
        )


    # --------------------------------------------------
    # Final recommendation
    # --------------------------------------------------

    print()
    print("=" * 60)
    print("FINAL RECOMMENDATION")
    print("=" * 60)

    print(
        "Recommendation:",
        final_recommendation
    )

    print()

    print(
        "Technical match:",
        round(
            adjusted_match,
            2
        ),
        "%"
    )

    print(
        "Experience match:",
        round(
            experience_match,
            2
        ),
        "%"
    )

    print(
        "Relevant Cloud/DevOps project:",
        "YES"
        if has_relevant_project
        else "NO"
    )

    print()

    print(
        "Missing hard requirements:",
        len(
            hard_missing_skills
        )
    )

    for item in hard_missing_skills:

        print(
            "-",
            item["skill"]
        )

    print()

    print(
        "Missing strong requirements:",
        len(
            strong_missing_skills
        )
    )

    for item in strong_missing_skills:

        print(
            "-",
            item["skill"]
        )

    print()
    print("Why:")

    for reason in decision_reasons:

        print(
            "-",
            reason
        )


    # --------------------------------------------------
    # Return structured result
    # --------------------------------------------------

    return {
        "job_title": job_analysis.job_title,

        "recommendation": final_recommendation,

        "technical_match": round(
            adjusted_match,
            2
        ),

        "resume_evidence_score": round(
            technical_match,
            2
        ),

        "transferable_credit": round(
            transferable_credit_points,
            2
        ),

        "technical_recommendation": (
            technical_recommendation
        ),

        "required_experience_years": (
            required_years
        ),

        "professional_experience_years": round(
            professional_experience_years,
            2
        ),

        "experience_match": round(
            experience_match,
            2
        ),

        "has_relevant_project": (
            has_relevant_project
        ),

        "matched_skills": [
            item["skill"]
            for item in matched_skills
        ],

        "partial_skills": [
            item["skill"]
            for item in partial_skills
        ],

        "missing_skills": [
            item["skill"]
            for item in missing_skills
        ],

        "missing_hard_requirements": [
            item["skill"]
            for item in hard_missing_skills
        ],

        "missing_strong_requirements": [
            item["skill"]
            for item in strong_missing_skills
        ],

        "category_scores": (
            category_scores
        ),

        "family_scores": (
            family_scores
        ),

        "reasons": (
            decision_reasons
        ),

        "resume_analysis": (
            resume_analysis.model_dump()
        )
    }


# --------------------------------------------------
# Local testing
# --------------------------------------------------

if __name__ == "__main__":

    with open(
        "resume.md",
        "r",
        encoding="utf-8"
    ) as resume_file:

        resume_text = resume_file.read()

    with open(
        "job.md",
        "r",
        encoding="utf-8"
    ) as job_file:

        job_text = job_file.read()


    result = match_job(
        resume_text,
        job_text
    )


    print()
    print("=" * 60)
    print("RETURNED RESULT")
    print("=" * 60)

    print(
        result
    )