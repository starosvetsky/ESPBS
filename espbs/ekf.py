"""Official EKF catalogue completion through the site's public GraphQL query."""
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from .universal import Client

API = 'https://hasura.ekfgroup.com/v1/graphql'

# This is the public operation used by the EKF category page. Hasura rejects
# arbitrary operations; retaining the published operation also keeps the
# adapter read-only and limited to catalogue data.
QUERY = r'''query CatalogCategoryProducts(
  $locale: String
  $slug: String
  $limit: Int
  $offset: Int
  $sortBy: [ekfgroup_catalog_category_product_order_by!]
  $where: ekfgroup_catalog_category_product_bool_exp = {}
) {
  categories: ekfgroup_catalog_categories(
    where: {
      active: { _eq: true }
      language: { code: { _eq: $locale } }
      slug: { _eq: $slug }
    }
  ) {
    ...CatalogCategoryProductsFragment

    productsTotal: products_aggregate(
      where: {
        _and: [
          $where
          { product: { price: { _gt: 0 }, active: { _eq: true } } }
        ]
      }
    ) {
      aggregate {
        count
      }
    }
  }
}

fragment CatalogCategoryProductsFragment on ekfgroup_catalog_categories {
  products(
    limit: $limit
    offset: $offset
    order_by: $sortBy
    where: {
      _and: [$where, { product: { price: { _gt: 0 }, active: { _eq: true } } }]
    }
  ) {
    product {
      ...CatalogProductFragment
      ...CatalogProductCardPropertiesFragment

      # Проба «9-го свойства» вместо count-агрегата: непустой список
      # означает, что свойств больше 8 (карточка показывает первые 8)
      hasMoreProperties: property_values(
        limit: 1
        offset: 8
        order_by: { sort_order: asc }
      ) {
        value
      }

      stocks(
        where: {
          warehouse_id: {
            _in: [
              "9f944d2f-f511-11e7-80d8-0cc47a0cbffe"
              "e6405e2b-6868-11e6-b17c-000c29c6d5f2"
              "471d8646-6868-11e6-b17c-000c29c6d5f2"
            ]
          }
        }
      ) {
        quantity
      }
    }
  }
}
fragment CatalogProductFragment on ekfgroup_catalog_products {
  active_im
  id
  name
  image
  is_new
  coefficient
  created_at
  hide_price
  hide_price_promo
  is_on_minpromtrog_register
  novelty
  parent_id
  popularity
  price
  price_base
  series
  slug
  slugify_vendor_code
  status
  vendor_code
  hyperlink
  unit_storage {
    name
  }
}
fragment CatalogProductCardPropertiesFragment on ekfgroup_catalog_products {
  property_values(limit: 8, order_by: { sort_order: asc }) {
    value
    property {
      ...CatalogProductPropertyFragment
    }
    property_unit {
      ...CatalogProductPropertyUnitFragment
    }
  }
}
fragment CatalogProductPropertyFragment on ekfgroup_catalog_properties {
  id
  name
}
fragment CatalogProductPropertyUnitFragment on ekfgroup_catalog_property_units {
  id
  name
}
'''


def category(url):
    parsed = urlsplit(url)
    pieces = parsed.path.rstrip('/').split('/')
    return (parsed.hostname == 'ekfgroup.com' and len(pieces) == 4 and
            pieces[1:3] == ['ru', 'catalog'] and pieces[3] != 'products')


def needs_api(html, url):
    if not category(url):
        return False
    soup = BeautifulSoup(html, 'html.parser')
    page = soup.select_one('.pagination [aria-setsize]')
    return bool(page and int(page.get('aria-setsize', '1')) > 1)


def product_links(url, root, stopped=lambda: False):
    slug = urlsplit(url).path.rstrip('/').rsplit('/', 1)[-1]
    client = Client(API, stopped, root=root)
    links = []
    expected = None
    offset = 0
    try:
        while expected is None or len(links) < expected:
            response = client.post_json(API, {'query': QUERY.rstrip(), 'variables': {
                'locale': 'ru', 'slug': slug, 'limit': 100, 'offset': offset,
                'sortBy': [{'product': {'popularity': 'desc'}}], 'where': {}}})
            if response.get('errors'):
                raise ValueError('EKF API: ' + str(response['errors'][0].get('message', 'ошибка ответа')))
            categories = response.get('data', {}).get('categories') or []
            if len(categories) != 1:
                raise ValueError('EKF API не вернул однозначную категорию: ' + slug)
            category_data = categories[0]
            current_expected = int(category_data.get('productsTotal', {}).get('aggregate', {}).get('count') or 0)
            if expected is not None and current_expected != expected:
                raise ValueError('Каталог EKF изменился во время постраничного чтения')
            expected = current_expected
            rows = category_data.get('products') or []
            before = len(links)
            for row in rows:
                product = row.get('product') or {}
                product_slug = product.get('slug')
                if isinstance(product_slug, str) and product_slug:
                    link = 'https://ekfgroup.com/ru/catalog/products/' + product_slug
                    if link not in links:
                        links.append(link)
            if len(links) == before and len(links) < expected:
                raise ValueError(f'EKF API остановился раньше конца раздела: {len(links)} из {expected}')
            offset += 100
    finally:
        client.close()
    if len(links) != expected:
        raise ValueError(f'EKF API вернул неполный раздел: {len(links)} из {expected}')
    return links
