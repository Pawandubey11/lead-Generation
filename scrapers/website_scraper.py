from scrapers.crawler import extract_socials_and_email


def scrape_website_data(url: str) -> dict:
    """Delegate website scraping to crawler's pooled, validated extractor."""
    return extract_socials_and_email(url)
