console.log("JobHunter TMU Collector content script loaded");

const REPROCESS_MIGRATION_KEY =
    "coverLetterFixReprocess20260919";

const REPROCESS_POSTING_IDS = new Set([
    "115808",
    "115789",
    "115809",
    "115825",
    "115592",
    "115797",
    "115794",
    "115806",
    "115793",
    "115835",
    "115810",
    "115795"
]);


function sleep(milliseconds) {

    return new Promise(resolve => {

        setTimeout(
            resolve,
            milliseconds
        );
    });
}


// Load posting IDs already processed by this extension
async function getSeenJobs() {

    const result = await chrome.storage.local.get(
        "seenPostingIds"
    );

    return result.seenPostingIds || [];
}


// One-time migration: allow the September 19 postings that were removed from
// DynamoDB to pass through the extension again after the cover-letter fix.
async function prepareCoverLetterFixReprocessing() {
    const storage = await chrome.storage.local.get([
        "seenPostingIds",
        REPROCESS_MIGRATION_KEY
    ]);

    if (storage[REPROCESS_MIGRATION_KEY]) {
        return;
    }

    const seenPostingIds = storage.seenPostingIds || [];
    const retainedPostingIds = seenPostingIds.filter(
        postingId => !REPROCESS_POSTING_IDS.has(String(postingId))
    );

    await chrome.storage.local.set({
        seenPostingIds: retainedPostingIds,
        [REPROCESS_MIGRATION_KEY]: true
    });

    console.log(
        "Prepared TMU postings for cover-letter reprocessing:",
        seenPostingIds.length - retainedPostingIds.length
    );
}


// Save a successfully processed posting ID
async function saveSeenJob(
    postingId,
    seenPostingIds
) {

    if (!seenPostingIds.includes(postingId)) {

        seenPostingIds.push(
            postingId
        );

        await chrome.storage.local.set({
            seenPostingIds: seenPostingIds
        });
    }
}


// Cheap title-based relevance filter
function isRelevantJob(job) {

    const title = job.title.toLowerCase();

    const relevantKeywords = [
        "software",
        "developer",
        "development",
        "programmer",
        "cloud",
        "devops",
        "infrastructure",
        "systems",
        "system",
        "network",
        "security",
        "cyber",
        "data",
        "database",
        "technical",
        "technology",
        "information technology",
        "it support",
        "help desk",
        "helpdesk",
        "service desk",
        "desktop support",
        "computer",
        "automation",
        "qa",
        "quality assurance",
        "testing",
        "machine learning",
        "ai ",
        "artificial intelligence",
        "site reliability",
        "sre",
        "platform",
        "operations engineer",
        "cloud engineer"
    ];

    return relevantKeywords.some(keyword =>
        title.includes(keyword)
    );
}


// Extract all jobs currently visible in the TMU table
function extractJobs() {

    const csrfToken = document.querySelector(
        'input[name="_csrf"]'
    )?.value;


    const jobs = [...document.querySelectorAll("table tr")]
        .map(row => {

            const cells = [...row.querySelectorAll("td")];

            // Ignore rows that are not real job rows
            if (cells.length < 9) {
                return null;
            }


            const jobLink = [...row.querySelectorAll("a")]
                .find(a =>
                    a.getAttribute("onclick")?.includes("postingId") &&
                    ![
                        "Apply",
                        "Shortlist",
                        "Applied"
                    ].includes(
                        a.innerText.trim()
                    )
                );


            if (!jobLink) {
                return null;
            }


            const onclick =
                jobLink.getAttribute("onclick");


            const postingId = onclick
                .match(/postingId':'(\d+)'/)?.[1];


            const action = onclick
                .match(/'action':'([^']+)'/)?.[1];


            const initialSearchAction = onclick
                .match(
                    /'initialSearchAction':'([^']+)'/
                )?.[1];


            const accessToPostings = onclick
                .match(
                    /'accessToPostings':'([^']+)'/
                )?.[1];


            const searchType = onclick
                .match(
                    /'searchType':'([^']*)'/
                )?.[1];


            const npfGroup = onclick
                .match(
                    /'npfGroup':'([^']*)'/
                )?.[1];


            const sortDirection = onclick
                .match(
                    /'sortDirection':'([^']*)'/
                )?.[1];


            return {

                postingId: postingId,

                title: jobLink.innerText
                    .trim()
                    .replace(/^NEW\s+/, ""),

                company: cells[5].innerText.trim(),

                term: cells[2].innerText.trim(),

                openings: cells[6].innerText.trim(),

                csrfToken: csrfToken,

                location: cells[7].innerText.trim(),

                deadline: cells[8].innerText.trim(),

                source: "tmu",

                // Temporary TMU request values
                action: action,
                initialSearchAction:
                    initialSearchAction,
                accessToPostings:
                    accessToPostings,
                searchType: searchType,
                npfGroup: npfGroup,
                sortDirection:
                    sortDirection
            };
        })

        .filter(job => job !== null);


    return jobs;
}


// Prevent two page-processing runs from overlapping
let isProcessing = false;

// Remember that the page changed while processing
let pendingPageCheck = false;

// Remember which page we most recently processed
let lastProcessedPage = null;


// Process all jobs currently shown on the page
async function processCurrentPage() {

    if (isProcessing) {

        console.log(
            "Job processing already running. Will check the new page when finished."
        );

        pendingPageCheck = true;

        return;
    }


    const currentPage = document.querySelector(
        'input[id^="currentPage"]'
    )?.value || "unknown";


    if (currentPage === lastProcessedPage) {

        console.log(
            "TMU page already processed:",
            currentPage
        );

        return;
    }


    const jobs = extractJobs();


    if (jobs.length === 0) {

        console.log(
            "No TMU jobs found yet."
        );

        return;
    }


    isProcessing = true;


    console.log(
        `Processing TMU page ${currentPage}`
    );


    console.log(
        "TMU jobs found:",
        jobs.length
    );


    console.table(
        jobs.map(job => ({
            postingId: job.postingId,
            title: job.title,
            company: job.company,
            term: job.term,
            openings: job.openings,
            location: job.location,
            deadline: job.deadline,
            source: job.source
        }))
    );


    const seenPostingIds =
        await getSeenJobs();


    try {

        for (
            let index = 0;
            index < jobs.length;
            index++
        ) {

            const job = jobs[index];


            try {

                // Skip jobs already collected
                if (
                    seenPostingIds.includes(
                        job.postingId
                    )
                ) {

                    console.log(
                        "Skipping already collected TMU job:",
                        job.postingId,
                        job.title
                    );

                    continue;
                }


                // Skip unrelated titles before fetching details
                if (!isRelevantJob(job)) {

                    console.log(
                        "Skipping unrelated TMU job:",
                        job.postingId,
                        job.title
                    );

                    continue;
                }


                console.log(
                    `Sending TMU job ${index + 1} of ${jobs.length}:`,
                    job.postingId,
                    job.title
                );


                const response =
                    await chrome.runtime.sendMessage({
                        type: "PROCESS_TMU_JOB",
                        job: job
                    });


                console.log(
                    `Background response for ${job.postingId}:`,
                    response
                );


                const awsStatus =
                    response?.awsResult
                        ?.aws_result
                        ?.status;


                if (
                    awsStatus === "PROCESSING" ||
                    awsStatus === "DUPLICATE"
                ) {

                    await saveSeenJob(
                        job.postingId,
                        seenPostingIds
                    );


                    console.log(
                        "Saved TMU job to local cache:",
                        job.postingId
                    );
                }


                // Wait before the next NEW relevant job
                if (
                    index < jobs.length - 1
                ) {

                    console.log(
                        "Waiting 3 seconds before next job..."
                    );

                    await sleep(3000);
                }

            } catch (error) {

                console.error(
                    "Failed to process TMU job:",
                    job.postingId,
                    job.title,
                    error
                );
            }
        }


        lastProcessedPage =
            currentPage;


        console.log(
            `Finished processing TMU page ${currentPage}.`
        );

    }  finally {

        isProcessing = false;


        if (pendingPageCheck) {

            pendingPageCheck = false;


            const visiblePage = document.querySelector(
                'input[id^="currentPage"]'
            )?.value;


            if (
                visiblePage &&
                visiblePage !== lastProcessedPage
            ) {

                console.log(
                    "Processing page that changed while previous page was running:",
                    visiblePage
                );

                processCurrentPage();
            }
        }
    }
}


// Apply storage migrations before processing the page that is already loaded.
prepareCoverLetterFixReprocessing()
    .then(() => processCurrentPage())
    .catch(error => {
        console.error(
            "Failed to prepare cover-letter reprocessing:",
            error
        );
    });


// Watch for TMU replacing the job table during pagination
let observerTimeout = null;


const observer = new MutationObserver(() => {

    clearTimeout(
        observerTimeout
    );


    // Wait briefly so TMU finishes replacing the table
    observerTimeout = setTimeout(
        () => {

            const currentPage =
                document.querySelector(
                    'input[id^="currentPage"]'
                )?.value;


            if (
                currentPage &&
                currentPage !== lastProcessedPage
            ) {

                console.log(
                    "Detected TMU page change:",
                    currentPage
                );

                processCurrentPage();
            }

        },
        1000
    );
});


observer.observe(
    document.body,
    {
        childList: true,
        subtree: true
    }
);
