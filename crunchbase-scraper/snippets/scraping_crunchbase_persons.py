# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
from adscrawl_scrapers import run as run_scraper
from adscrawl_scrapers import managed
# https://gist.github.com/scrapfly-dev/6b11f57529fd2209146aec803395590e
import json
import os
import asyncio
import jmespath

from typing import List, Dict
from adscrawl_scrapers import Response, Request, ScraperClient

BASE_CONFIG = {
    'render': True,

}

CLIENT = ScraperClient()

def _unescape_angular(text):
    """Helper function to unescape Angular quoted text"""
    ANGULAR_ESCAPE = {
        "&a;": "&",
        "&q;": '"',
        "&s;": "'",
        "&l;": "<",
        "&g;": ">",
    }
    for from_, to in ANGULAR_ESCAPE.items():
        text = text.replace(from_, to)
    return text

def _reduce_person_dataset(dataset: dict) -> Dict:
    """Reduce person dataset to a smaller subset of the most important fields"""
    parsed = jmespath.search(
        """{
        name: properties.identifier.value,
        title: properties.title,
        description: properties.short_description,
        type: properties.layout_id,

        gender: cards.overview_fields.gender,
        location_groups: cards.overview_fields.location_group_identifiers[].value,
        location: cards.overview_fields.location_identifiers[].value,
        current_jobs: cards.jobs_summary.num_current_jobs,
        past_jobs: cards.jobs_summary.num_past_jobs,

        education: cards.education_image_list[].{
            school: school_identifier.value,
            type: type_name
        },

        timeline: cards.timeline.entities[].properties.identifier.value
        ,

        investments: cards.investments_list[].{
            identifier: {
                uuid: identifier.uuid,
                value: identifier.value,
                permalink: identifier.permalink,
                entity_def_id: identifier.entity_def_id
            },
            organization_identifier: {
                uuid: organization_identifier.uuid,
                value: organization_identifier.value,
                permalink: organization_identifier.permalink,
                entity_def_id: organization_identifier.entity_def_id
            },
            funding_round_identifier: {
                uuid: funding_round_identifier.uuid,
                value: funding_round_identifier.value,
                permalink: funding_round_identifier.permalink,
                entity_def_id: funding_round_identifier.entity_def_id
            }
        },

        exits: cards.exits_image_list[].{
            name: identifier.value,
            short_description: short_description
        }

        investing_overview: cards.investor_overview_headline,
        linkedin: cards.overview_fields2.linkedin.value,
        twitter: cards.overview_fields2.twitter.value,
        facebook: cards.overview_fields2.facebook.value,

        current_advisor_jobs: cards.investor_overview_headline.num_current_advisor_jobs,
        founded_orgs: cards.investor_overview_headline.num_founded_organizations,
        portfolio_orgs: cards.investor_overview_headline.num_portfolio_organizations,
        rank_principal_investor: cards.investor_overview_headline.rank_principal_investor
    }""",
        dataset,
    )
    return parsed


def parse_person(result: Response) -> Dict:
    app_state_data = result.selector.css("script#ng-state::text").get()
    if not app_state_data:
        app_state_data = _unescape_angular(result.selector.css("script#client-app-state::text").get() or "")
    app_state_data = json.loads(app_state_data)
    cache_keys = list(app_state_data["HttpState"])
    dataset_key = next(key for key in cache_keys if "data/entities" in key)
    dataset = app_state_data["HttpState"][dataset_key]["data"]
    return _reduce_person_dataset(dataset)


@managed
async def scrape_person(url: str) -> Dict:
    print(f"scraping person: {url}")
    result = await CLIENT.fetch(Request(url, **BASE_CONFIG))
    return parse_person(result)


@managed
async def main():
    url = "https://www.crunchbase.com/person/elon-musk"
    person_data = await scrape_person(url)

    # save the results to a json file
    with open("person_data.json", "w", encoding="utf-8") as f:
        json.dump(person_data, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    run_scraper(main())
