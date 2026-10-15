"""Synthetic arbitrary-domain, multibrand, replay and network-boundary tests."""
import json
import tempfile
import unittest
from unittest.mock import Mock, patch

from espbs.directory import Directory, Enricher, detect, probe
from espbs.universal import Adapter, Client, public_url, public_addresses
from espbs.jobs import Job
from espbs.storage import Batch
from espbs.archive import export_batch, verify_archive
from espbs.retention import confirm_copy, cleanup


def html(brand='Alpha', mpn='X-1', image='/official.png'):
    return '<script type="application/ld+json">'+json.dumps({
        '@type':'Product','name':brand+' '+mpn,'brand':{'name':brand},'mpn':mpn,
        'description':'Official test description','image':image,
        'additionalProperty':[{'name':'Ports','value':'8'}],
        'offers':{'price':'999','priceCurrency':'RUB'}})+'</script>'


def record(brand='Alpha', mpn='X-1'):
    item=Adapter().product(html(brand,mpn),'https://shop.example/product/'+mpn)
    item['offer']['price_text']='123'
    return item


class DirectoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=self.temp.name;self.directory=Directory(self.root)

    def manufacturer(self,brand='Alpha'):
        return self.directory.save_manufacturer({'brand':brand,'home_url':'https://'+brand.lower()+'.example/',
                                                 'template':'https://'+brand.lower()+'.example/product/{mpn}'})

    def test_profile_and_structured_preview(self):
        url='https://shop.example/product/x'
        self.directory.save_profile(url,{'name':'h1','manufacturer':'.brand','mpn':'.mpn'})
        config=detect(self.root,url)
        self.assertEqual(config['selectors']['name'],'h1')
        with patch('espbs.directory.Client') as cls:
            cls.return_value.get.return_value='<h1>Item</h1><b class="brand">Alpha</b><b class="mpn">X-1</b>'
            result=probe(self.root,url)
            self.assertTrue(result['can_start'])
            self.assertEqual(result['samples'][0]['mpn'],'X-1')
        with self.assertRaises(ValueError):
            self.directory.save_profile(url,{'script':'anything'})

    def test_listing_does_not_pick_related_products(self):
        adapter=Adapter()
        with self.assertRaises(ValueError):
            adapter.product(html()+html('Beta'),'https://shop.example/catalog/')
        listing=Adapter({'product_links':'a.product','next_links':'a.next'})
        urls,pages=listing.listing('<a class="product" href="/p/1">one</a><a class="product" href="https://evil.example/">bad</a><a class="next" href="/page2">next</a>','https://shop.example/')
        self.assertEqual(urls,['https://shop.example/p/1']);self.assertEqual(pages,['https://shop.example/page2'])

    def test_multibrand_cache_exact_identity(self):
        self.manufacturer();self.manufacturer('Beta')
        enricher=Enricher(self.root); client=Mock()
        client.get.side_effect=lambda url:html('Beta' if 'beta.' in url else 'Alpha')
        with patch.object(enricher,'client',return_value=client):
            alpha=enricher.enrich(record());beta=enricher.enrich(record('Beta'))
            self.assertEqual(alpha['enrichment']['status'],'MATCHED')
            self.assertEqual(beta['enrichment']['status'],'MATCHED')
            self.assertEqual(alpha['offer']['price_text'],'123')
            self.assertEqual(alpha['images'],['https://alpha.example/official.png'])
            self.assertEqual(client.get.call_count,2)
            again=Enricher(self.root).enrich(record())
            self.assertTrue(again['enrichment']['cached'])
            mismatch=enricher.enrich(record('Alpha','X-1_DC'))
            self.assertEqual(mismatch['enrichment']['status'],'MISMATCH')
            self.assertEqual(mismatch['images'],[])

    def test_directory_validation_and_missing_mapping(self):
        self.directory.save_manufacturer({'brand':'Alpha','home_url':'https://alpha.example/'})
        enricher=Enricher(self.root)
        self.assertEqual(enricher.enrich(record())['enrichment']['status'],'NEEDS_MAPPING')
        self.assertEqual(enricher.enrich(record('Unknown'))['enrichment']['status'],'NO_MANUFACTURER')
        with self.assertRaises(ValueError):
            self.directory.save_mapping({'brand':'Alpha','mpn':'X-1','url':'https://other.example/x'})
        with self.assertRaises(ValueError):
            self.directory.save_manufacturer({'brand':'Store','home_url':'https://olnisa.ru/'})
        self.directory.save_mapping({'brand':'Alpha','mpn':'X-1','url':'https://alpha.example/card'})
        self.assertEqual(Directory(self.root).resolve('ALPHA','x-1')[1],'https://alpha.example/card')
        self.directory.save_manufacturer({'brand':'Alpha','home_url':'https://new-alpha.example/'})
        self.assertIsNone(self.directory.resolve('Alpha','X-1')[1])

    def test_separate_queue_survives_parent_cleanup_and_resumes(self):
        parent=Job.create(self.root,2)
        batch=Batch(self.root,parent.id)
        batch.add(record());batch.add(record('Beta','X-2'))
        with parent.db() as db:db.execute("UPDATE job SET state='COMPLETED'")
        child=Job.create_enrichment(parent)
        archive=export_batch(batch,self.root+'/exports')
        confirm_copy(parent,verify_archive(archive));cleanup(parent,parent.id)
        self.assertEqual(batch.info()['record_count'],0)
        result=child.run(callback=lambda e:child.stop() if e['kind']=='saved' else None)
        self.assertEqual(result['state'],'STOPPED');self.assertEqual(result['completed'],1)
        self.assertEqual(Job(self.root,child.id).run()['state'],'COMPLETED')
        self.assertEqual(Batch(self.root,child.id).info()['record_count'],2)
        self.assertEqual(child.info()['enrichment_counts']['NO_MANUFACTURER'],2)
        child_archive=export_batch(Batch(self.root,child.id),self.root+'/exports')
        confirm_copy(child,verify_archive(child_archive));cleanup(child,child.id)
        with child.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM inputs').fetchone()[0],0)

    def test_automatic_followup(self):
        parent=Job.create(self.root,1,'auto','https://shop.example/p',auto_enrich=True)
        client=Mock();client.get.return_value=html()
        with patch('espbs.api.launch_worker') as launch:
            result=parent.run(client)
        self.assertEqual(result['state'],'COMPLETED');self.assertIn('child_id',result)
        self.assertEqual(Job(self.root,result['child_id']).info()['parent_id'],parent.id)
        launch.assert_called_once()

    def test_large_snapshot_is_background_and_blocks_early_cleanup(self):
        parent=Job.create(self.root,101)
        batch=Batch(self.root,parent.id)
        for number in range(101):batch.add(record('Unknown',str(number)))
        with parent.db() as db:db.execute("UPDATE job SET state='COMPLETED'")
        child=Job.create_enrichment(parent)
        self.assertEqual(child.info()['discovered'],0)
        archive=export_batch(batch,self.root+'/exports')
        confirm_copy(parent,verify_archive(archive))
        with self.assertRaisesRegex(ValueError,'очередь'):
            cleanup(parent,parent.id)
        result=child.run(callback=lambda e:child.stop() if e['kind']=='snapshot' else None)
        self.assertEqual(result['state'],'STOPPED')
        self.assertEqual(result['discovered'],100)
        result=child.run()
        self.assertEqual(result['completed'],101)
        self.assertTrue(result['snapshot_ready'])
        self.assertEqual(result['enrichment_counts']['NO_MANUFACTURER'],101)
        cleanup(parent,parent.id)
        self.assertEqual(Batch(self.root,child.id).info()['record_count'],101)

    def test_collection_over_old_limit_and_20_pages(self):
        job=Job.create(self.root,1_000_000,'auto','https://shop.example/page/0',
                       selectors={'product_links':'a.product','next_links':'a.next'})
        client=Mock()
        def get(url):
            if '/page/' not in url:
                return html('Unknown',url.rsplit('/',1)[-1])
            page=int(url.rsplit('/',1)[-1])
            products=''.join(f'<a class="product" href="/product/{page*5+i}">p</a>' for i in range(5))
            return products+(f'<a class="next" href="/page/{page+1}">next</a>' if page<20 else '')
        client.get.side_effect=get
        result=job.run(client)
        self.assertEqual(result['state'],'COMPLETED')
        self.assertEqual(result['completed'],105)
        self.assertEqual(result['discovered'],105)
        self.assertEqual(Batch(self.root,job.id).info()['record_count'],105)


class PublicNetworkTests(unittest.TestCase):
    def test_url_and_dns_boundaries(self):
        for url in ['http://example.com','https://localhost/','https://127.0.0.1/','https://169.254.169.254/',
                    'https://example.com:8765/','https://user:pass@example.com/']:
            with self.assertRaises(ValueError):public_url(url)
        with patch('socket.getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]):
            with self.assertRaises(ValueError):public_addresses('public.example')
        with self.assertRaises(ValueError):Client('https://one.example/').get('https://two.example/')

    def test_robots_and_redirect_fail_closed(self):
        client=Client('https://shop.example/')
        with patch.object(client,'_request',return_value='User-agent: *\nDisallow: /product/*') as get:
            with self.assertRaisesRegex(ValueError,'robots'):client.get('https://shop.example/product/1')
            self.assertEqual(get.call_count,1)
        response=Mock(status=302)
        connection=Mock();connection.getresponse.return_value=response
        with patch('espbs.universal.public_addresses',return_value=['93.184.215.14']),patch('http.client.HTTPSConnection',return_value=connection):
            with self.assertRaisesRegex(ValueError,'302'):Client('https://shop.example/').get('https://shop.example/p')
            connection.close.assert_called_once()


if __name__=='__main__':unittest.main()
