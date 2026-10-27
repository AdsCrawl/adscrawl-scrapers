# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
"""
This example run script shows how to run the Indeed.com scraper defined in ./indeed.py
It scrapes job data and saves it to ./results/

To run this script set the env variable $ADSCRAWL_API_KEY with your AdsCrawl API key:
$ export ADSCRAWL_API_KEY="your key from https://app.adscrawl.net/dashboard/keys/"
"""
from adscrawl_scrapers import run as run_scraper
import asyncio
import json
from pathlib import Path
import indeed

output = Path(__file__).parent / "results"
output.mkdir(exist_ok=True)


async def run():


    print("running Indeed scrape and saving results to ./results directory")

    url = "https://www.indeed.com/jobs?q=python&l=Texas"
    result_search = await indeed.scrape_search(url, max_results=10)
    output.joinpath("search.json").write_text(json.dumps(result_search, indent=2, ensure_ascii=False), encoding="utf-8")

    jobs = ["851525cd1dc01964", "0e633abc66767644"]
    result_jobs = await indeed.scrape_jobs(jobs)
    output.joinpath("jobs.json").write_text(json.dumps(result_jobs, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    run_scraper(run())
