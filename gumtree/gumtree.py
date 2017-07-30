from bs4 import BeautifulSoup
import sys
import re
import requests
from urllib.parse import urljoin

class AdSoldException(Exception):
    def __init__(self, message):
        self.message = message

class GSearch:
    def __init__(self, url):
        item_urls = self.scrape_pages(url)

        self.items = []
        print('Scraping items, max: %d' % len(item_urls))
        for item_url in item_urls:
            print(item_url)
            self.items.append(GItem(item_url))

    def scrape_pages(self, url):
        """Scrape the urls in each page for items
        """
        page_urls = self.get_page_urls(url)

        item_urls = []
        print('Scraping pages, max: %d' % len(page_urls))
        for page_url in page_urls:
            print(page_url)
            result = requests.get(page_url)
            soup = BeautifulSoup(result.content, 'html.parser')

            listings = soup.find_all('a',
                                    {'class':'ad-listing__title-link',
                                     'itemprop':'url'},
                                     href=True)

            for listing in listings:
                item_urls.append(listing['href'])

        item_urls = [urljoin(url, item) for item in item_urls]

        return item_urls


    def scrape_page_pool(self, url):
        """To be used for multithreading
        """
        pass

    def get_page_urls(self, url):
        """Checks the url in the 'last page' pagination button
        to determine how many pages exist

        If 'last page' doesn't exist, there must only be one page!

        Generates urls of the pages based on this 'max' number.
        """
        result = requests.get(url)
        result.raise_for_status()

        soup = BeautifulSoup(result.content, 'html.parser')
        paginator = soup.find('div', {'class':'paginator'})
        last_button = paginator.find('a',
            {'class':'paginator__button-last'}, 
            href=True,)

        max_page = 1
        if last_button:
            href = last_button['href']
            reg_result = re.search('\/page-([0-9]*?)\/', href)
            max_page = int(reg_result.group(1))

        page_urls = []
        for idx in range(1, max_page+1):
            page_urls.append(url.replace('page-1', 'page-%d' % idx))

        return page_urls


class GItem:
    def __init__(self, url):
        result = requests.get(url)
        result.raise_for_status()

        soup = BeautifulSoup(result.content, 'html.parser')
        self.ad_id, self.url = self.parse_ad_id(url)
        self.title = self.parse_title(soup)
        self.price, self.negotiable = self.parse_price(soup)
        self.images = self.parse_images(soup)
        self.location = self.parse_location(soup)
        self.user = self.parse_user(soup)
        self.description = self.parse_description(soup)

        self.extras = self.parse_ad_attributes(soup)

    def parse_ad_id(self, url):
        ad_id = re.search('\/([0-9]*?)\/?$', url).group(1)
        url = 'https://www.gumtree.com.au/s-ad/' + ad_id

        return ad_id, url

    def parse_title(self, soup):
        return soup.find('h1', {'id': 'ad-title'}).text.strip()

    def parse_price(self, soup):
        ad_price = soup.find('div', {'id': 'ad-price'})
        text = ad_price.text.strip()
        if ad_price:
            result = re.search('\$([0-9]*\.[0-9]{2})', text)
            if result:
                price = result.group(1)
            else:
                price = None

            negotiable = 'Negotiable' in text
        else:
            raise AdSoldException('"%s" has been sold.' % self.title)

        return price, negotiable

    def parse_images(self, soup):
        images = []
        gallery = soup.find('ul', {'class': 'gallery__main-viewer-list'})

        if gallery:
            data_images = gallery.find_all('span')
            for data_image in data_images:
                if data_image.has_attr('data-responsive-image'):
                    data = data_image['data-responsive-image']
                    image = re.search('large: \'(.*?)\'', data).group(1)
                    images.append(image)

        return images

    def parse_location(self, soup):
        ad_map = soup.find('div', {'id':'ad-map'})
        span = ad_map.find('span')

        return span['data-address']

    def parse_user(self, soup):
        container = soup.find('div', {'id': 'sticky-contact-offer'})
        profile = container.find('div',
            {'class': 'seller-profile__seller-detail'})
        return GUser(profile)

    def parse_description(self, soup):
        return soup.find('div', {'id':'ad-description-details'}).text.strip()

    def parse_ad_attributes(self, soup):
        extras = {}
        container = soup.find('div', {'id': 'ad-attributes'})

        # Jobs do not use 'ad-attributes'...
        if container:        
            sections = container.find_all('dl')

            for section in sections:
                key = section.find('dt').text.strip() \
                    .replace(':','').replace(' ', '_').lower()
                value = section.find('dd').text.strip()

                if key not in extras:
                    extras[key] = value
                else:
                    raise NotImplementedError('Cannot handle duplicate key')

        return extras


class GUser:
    def __init__(self, profile):
        href = profile.find('a', href=True)['href']
        name, userid = re.match('/s-seller/(.*?)/(.*?)$', href).groups()

        member_since = profile.find('span',
            {'class':'seller-profile__member-since'}).text

        created = re.match('Gummie since (.*?)$', member_since).group(1)

        self.name = name
        self.userid = userid
        self.created = created

if __name__ == '__main__':
    url = 'https://www.gumtree.com.au/s-belmont/page-1/l3008329?price-type=free'
    try:
        item = GSearch(url)
        import pdb;pdb.set_trace()
    except AdSoldException as e:
        print(e.message)
