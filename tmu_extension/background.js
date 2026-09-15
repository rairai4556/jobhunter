console.log("JobHunter background service worker loaded");


function sleep(milliseconds) {
    return new Promise(resolve => {
        setTimeout(resolve, milliseconds);
    });
}


async function fetchTMUJob(job, attempt = 1) {

    console.log(
        `Fetching TMU job ${job.postingId}, attempt ${attempt}`
    );

    const response = await fetch(
        "https://recruitstudents.torontomu.ca/myAccount/coop/postings.htm",
        {
            method: "POST",

            credentials: "include",

            headers: {
                "Content-Type": "application/x-www-form-urlencoded"
            },

            body: new URLSearchParams({
                action: job.action,
                initialSearchAction: job.initialSearchAction,
                searchType: job.searchType || "",
                accessToPostings: job.accessToPostings || "",
                postingId: job.postingId,
                npfGroup: job.npfGroup || "",
                sortDirection: job.sortDirection || "",
                _csrf: job.csrfToken,
                rand: Math.floor(
                    Math.random() * 100000
                ).toString()
            })
        }
    );


    const html = await response.text();




    const startMarker = "Job Description:";
    const endMarker = "Targeted Degrees and Disciplines:";

    const startIndex = html.indexOf(
        startMarker
    );

    const endIndex = html.indexOf(
        endMarker,
        startIndex
    );


    if (
        startIndex === -1 ||
        endIndex === -1
    ) {

        console.log(
            "Could not find description markers"
        );

        console.log(
            "Has Job Description marker:",
            startIndex !== -1
        );

        console.log(
            "Has Targeted Degrees marker:",
            endIndex !== -1
        );


        if (attempt === 1) {

            console.log(
                "Waiting 5 seconds before retry..."
            );

            await sleep(5000);

            return fetchTMUJob(
                job,
                2
            );
        }


        return {
            success: false,
            error: "Could not find job description after retry"
        };
    }


    const descriptionHtml = html.slice(
        startIndex + startMarker.length,
        endIndex
    );


    const descriptionText = descriptionHtml
        .replace(/<script[\s\S]*?<\/script>/gi, " ")
        .replace(/<style[\s\S]*?<\/style>/gi, " ")
        .replace(/<[^>]+>/g, " ")
        .replace(/&nbsp;/gi, " ")
        .replace(/&amp;/gi, "&")
        .replace(/&lt;/gi, "<")
        .replace(/&gt;/gi, ">")
        .replace(/&quot;/gi, '"')
        .replace(/&#39;/gi, "'")
        .replace(/\s+/g, " ")
        .trim();


    console.log(
        "Extracted description length:",
        descriptionText.length
    );

    const normalizedJob = {
        postingId: job.postingId,
        title: job.title,
        company: job.company,
        location: job.location,
        deadline: job.deadline,
        source: "tmu",
        job_text: descriptionText
    };


    console.log(
        "Sending job to local collector:",
        normalizedJob.postingId,
        normalizedJob.title
    );


    const collectorResponse = await fetch(
        "http://127.0.0.1:8765",
        {
            method: "POST",

            headers: {
                "Content-Type": "application/json"
            },

            body: JSON.stringify(
                normalizedJob
            )
        }
    );


    const result =
        await collectorResponse.json();


    console.log(
        "Local collector result:",
        result
    );


    return {
        success: true,
        htmlLength: html.length,
        awsResult: result
    };
}


chrome.runtime.onMessage.addListener(
    (message, sender, sendResponse) => {

        if (message.type !== "PROCESS_TMU_JOB") {
            return;
        }


        console.log(
            "Background received TMU job:",
            message.job.postingId,
            message.job.title
        );


        const job = message.job;


        fetchTMUJob(job)

            .then(result => {

                sendResponse(
                    result
                );

            })

            .catch(error => {

                console.error(
                    "TMU job processing failed:",
                    error
                );

                sendResponse({
                    success: false,
                    error: error.message
                });

            });


        return true;
    }
);