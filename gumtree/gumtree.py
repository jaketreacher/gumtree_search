from bs4 import BeautifulSoup
from multiprocessing.dummy import Pool
import pickle
import sys
import re
import requests
from urllib.parse import urljoin, urlparse

_CHROME = {'User-Agent': 'Mozilla/5.0 (Windows NT 6.1) AppleWebKit/537.36 ' \
           '(KHTML, like Gecko) Chrome/41.0.2228.0 Safari/537.36'}

# Used for threading to show progress
count = 0
total = 0

class AdSoldException(Exception):
    def __init__(self, message):
        self.message = message

class GSearch:
    def __init__(self, url):
        item_urls = self.scrape_pages(url)

        self.items = []
        print('Scraping items, found: %d' % len(item_urls))
        
        global count, total
        count = 1
        total = len(item_urls)
        with Pool(8) as pool:
            self.items = pool.map(self.gitem_pool, item_urls)

        self.errors = [item for item in self.items 
            if not isinstance(item, GItem)]

        self.items = [item for item in self.items 
            if isinstance(item, GItem)]

    def gitem_pool(self, url):
        print_progress(url)
        try:
            return GItem(url)
        except Exception as e:
            return (url, e)

    def scrape_pages(self, url):
        """Scrape the urls in each page for items
        """
        page_urls = self.get_page_urls(url)

        print('Scraping pages, found: %d' % len(page_urls))
        global count, total
        count = 1
        total = len(page_urls)
        with Pool(8) as pool:
            item_urls = pool.map(self.scrape_page_pool, page_urls)

        #flatten list
        item_urls = [item for sub_list in item_urls for item in sub_list]

        #convert to absolute url
        item_urls = [urljoin(url, item) for item in item_urls]

        return item_urls


    def scrape_page_pool(self, url):
        """To be used for threading
        """
        print_progress(url)
        item_urls = []
        result = requests.get(url, headers=_CHROME)
        soup = BeautifulSoup(result.content, 'html.parser')

        listings = soup.find_all('a',
                                {'class':'ad-listing__title-link',
                                 'itemprop':'url'},
                                 href=True)

        for listing in listings:
            item_urls.append(listing['href'])

        return item_urls

    def get_page_urls(self, url):
        """Checks the url in the 'last page' pagination button
        to determine how many pages exist

        If 'last page' doesn't exist, there must only be one page!

        Generates urls of the pages based on this 'max' number.
        """
        result = requests.get(url, headers=_CHROME)
        result.raise_for_status()

        soup = BeautifulSoup(result.content, 'html.parser')
        paginator = soup.find('div', {'class':'paginator'})
        last_button = paginator.find('a',
            {'class':'paginator__button-last'}, 
            href=True)

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
        result = requests.get(url, headers=_CHROME)
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
        if ad_price:
            text = ad_price.text.strip()
            result = re.search('\$([0-9]*\.[0-9]{2})', text)
            if result:
                price = result.group(1)
            else:
                price = None

            negotiable = 'Negotiable' in text

            return price, negotiable
        else:
            return None, None

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

            # Clear bogus sections with no content
            sections = [sect for sect in sections if sect.text]
            for section in sections:
                dt = section.find('dt')
                key = dt.text.strip() \
                    .replace(':','') \
                    .replace(' ', '_') \
                    .lower()

                dd = section.find('dd')
                value = dd.text.strip()

                if key not in extras:
                    extras[key] = value
                else:
                    raise NotImplementedError('Cannot handle duplicate key')

        return extras


class GUser:
    def __init__(self, profile):
        a_sect = profile.find('a', href=True)
        result = re.match('/s-seller/(.*?)/(.*?)$', a_sect['href'])
        if result:
            name, userid = result.groups()
        else:
            name = a_sect.text.strip()
            userid = a_sect['href']

        member_since = profile.find('span',
            {'class':'seller-profile__member-since'}).text

        created = re.match('Gummie since (.*?)$', member_since).group(1)

        self.name = name
        self.userid = userid
        self.created = created

def prepare_args(urls):
    total = len(urls)
    args = list(enumerate(urls))
    args = [(url, idx+1, total) for idx, url in args]
    return args

def print_progress(url):
    global count, total
    url = limit(url)

    # count += 1 on the same line for threading purposes
    # if it is moved to a second line, multiple threads will print
    #   the same number
    print("{:60} | ({}/{})".format(url, count, total)); count += 1

def limit(string, print_length=58):
    """Limit the length of a string to print_length characters
    Replaces the middle with ...
    """
    if len(string) > print_length:
        trim = int((print_length-3)/2)
        return string[:trim] + '...' + string[-trim:]
    else:
        return string

def prepare_url(url):
    url_p = urlparse(url)

    # ensure page-1 appears in the url
    path = url_p.path
    result = re.search('(page-[0-9]*?)\/', path)
    if result:
        path = path.replace(result.group(1), 'page-1')
    else:
        # insert page-1 as second last path segment
        path = path.split('/')
        path.insert(-1, 'page-1')
        path = '/'.join(path)
    url_p = url_p._replace(path=path)

    # add pageSize=96 query so it forces more results
    query = url_p.query
    query = query.split('&')
    query.append('pageSize=96')
    query = '&'.join(query)
    url_p = url_p._replace(query=query)

    return url_p.geturl()

if __name__ == '__main__':
    url = sys.argv[1]
    url = prepare_url(url)
    gsearch = GSearch(url)
    with open('result.pkl', 'wb') as file:
        pickle.dump(gsearch, file)
