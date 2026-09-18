from ai_extractor import get_openai_client


def generate_cover_letter(resume_text, job_text, job_title, company):
    client = get_openai_client()

    response = client.responses.create(
        model="gpt-5.6-luna",
        input=[
            {
                "role": "system",
                "content": """
Write a concise, tailored cover letter for a job application.

Rules:
- Use only facts supported by the supplied resume and job posting.
- Never invent experience, credentials, metrics, or personal details.
- Connect the strongest relevant projects, skills, and experience to
  the employer's stated needs.
- Use a professional, direct tone suitable for a student or early-career
  applicant.
- Write 220 to 300 words.
- Start with "Dear Hiring Team,".
- End with "Sincerely," followed by "Raihan".
- Return only the finished cover letter, with no notes or markdown.
"""
            },
            {
                "role": "user",
                "content": (
                    f"Job title: {job_title}\n"
                    f"Company: {company}\n\n"
                    f"RESUME:\n{resume_text}\n\n"
                    f"JOB POSTING:\n{job_text}"
                )
            }
        ]
    )

    return response.output_text.strip()
