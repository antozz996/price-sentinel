import asyncio, hashlib, hmac, json, os, time
from uuid import uuid4

import httpx, psycopg2

from app.main import app
from app.services.auth import create_access_token

DSN=os.environ.get('TEST_DATABASE_DSN','postgresql://sentinel_test:sentinel_test_local_only@db:5432/price_sentinel_s5_test')
VENUE_A=str(uuid4()); VENUE_B=str(uuid4()); ORDER_A=str(uuid4()); ORDER_B=str(uuid4()); PO_A=str(uuid4()); PO_B=str(uuid4())
ITEMS=[str(uuid4()) for _ in range(7)]; EVENT=str(uuid4()); results=[]
def check(name,value):
    if not value: raise AssertionError(name)
    results.append(name)
def scalar(sql,args=()):
    with psycopg2.connect(DSN) as c:
        with c.cursor() as cur: cur.execute(sql,args); row=cur.fetchone(); return row[0] if row else None

def seed():
    with psycopg2.connect(DSN) as c:
      with c.cursor() as x:
        x.execute("""
        insert into location(id,nome_struttura,piva_riferimento,tipologia) values (1,'Test Venue A','00000000001','ristorante'),(2,'Test Venue B','00000000002','ristorante');
        insert into utenti(id,email,password_hash,ruolo,location_id,attivo,refresh_token_version) values (1,'admin@test.local','x','admin',null,true,1),(2,'manager@test.local','x','manager',1,true,1);
        insert into fornitori(id,partita_iva,nome_azienda,attivo_whitelist) values (1,'10000000001','Supplier A',true),(2,'10000000002','Supplier B',true);
        insert into products(id,sku_interno,canonical_name,normalized_name,comparison_unit,is_commodity,is_active,unit_count,created_at,updated_at) values
          (1,'SKU1','Exact','exact','pz',false,true,1,now(),now()),(2,'SKU2','Alias','alias','pz',false,true,1,now(),now()),
          (3,'SKU3','EAN','ean','pz',false,true,1,now(),now()),(4,'SKU4','Price','price','pz',false,true,1,now(),now()),
          (5,'SKU5','Unit','unit','pz',false,true,1,now(),now()),(6,'SKU6','Missing','missing','pz',false,true,1,now(),now()),
          (7,'SKU7','Tolerance','tolerance','pz',false,true,1,now(),now()),(8,'SKU8','Unordered','unordered','pz',false,true,1,now(),now());
        insert into supplier_product_aliases(id,supplier_id,product_id,supplier_code,raw_description,normalized_description,ean,status,confidence_score,source,first_seen_at,last_seen_at,created_at,updated_at) values
          (1,1,2,'ALIAS-2','Alias','alias',null,'approved',1,'test',now(),now(),now(),now()),
          (2,1,3,null,'EAN','ean','8000000000003','approved',1,'test',now(),now(),now(),now());
        insert into listino_master(id,fornitore_id,sku_interno,descrizione,prezzo_pattuito,unita_misura,data_inizio_validita) values
          (1,1,'SKU4','Price',10,'pz','2026-01-01'),(2,1,'SKU7','Tolerance',10,'pz','2026-01-01');
        insert into xml_raw(id,payload,hash_idempotenza,source,stato_ingestion,data_ricezione) values
          (1,'<x/>','aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa','upload_manuale','parsato',now()),
          (2,'<x/>','bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb','upload_manuale','parsato',now()),
          (3,'<x/>','cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc','upload_manuale','parsato',now());
        insert into fatture(id,xml_raw_id,fornitore_id,location_id,numero_documento,data_documento,data_ricezione_sdi,tipo_documento,totale_imponibile,marker) values
          (1,1,1,1,'INV-VALID','2026-07-24','2026-07-24','TD01',200,'nessuno'),
          (2,2,1,2,'INV-WRONG-VENUE','2026-07-24','2026-07-24','TD01',10,'nessuno'),
          (3,3,2,1,'INV-WRONG-SUPPLIER','2026-07-24','2026-07-24','TD01',10,'nessuno');
        insert into righe_fattura(id,fattura_id,numero_linea,codice_fornitore_raw,descrizione_fornitore_raw,sku_interno,prezzo_unitario_fatturato,sconto_percentuale,prezzo_netto_normalizzato,quantita,unita_misura_fattura,is_omaggio,stato_matching) values
          (1,1,1,'EXACT','Exact','SKU1',5,0,5,5,'pz',false,'matched'),
          (2,1,2,'ALIAS-2','Alias',null,4,0,4,6,'pz',false,'matched'),
          (3,1,3,'8000000000003','EAN',null,3,0,3,2,'pz',false,'matched'),
          (4,1,4,'PRICE','Price','SKU4',12,0,12,2,'pz',false,'matched'),
          (5,1,5,'UNIT','Unit','SKU5',1,0,1,1,'kg',false,'matched'),
          (6,1,6,'TOL','Tolerance','SKU7',10.005,0,10.005,1,'pz',false,'matched'),
          (7,1,7,'UNORD','Unordered','SKU8',2,0,2,1,'pz',false,'matched'),
          (8,1,8,null,'Product 6',null,1,0,1,1,'pz',false,'no_match'),
          (9,1,9,'EXACT','Exact','SKU1',5,0,5,5,'pz',false,'matched');
        """)
        x.execute("""insert into liquidstock_supplier_orders(id,liquidstock_order_id,liquidstock_supplier_order_id,liquidstock_venue_id,venue_name_snapshot,liquidstock_supplier_id,supplier_id,supplier_name_snapshot,order_version,status,sent_at,requested_delivery_date,received_at,last_event_id,created_at,updated_at) values
          (1,%s,%s,%s,'Venue A',%s,1,'Supplier A',1,'received',now(),'2026-07-23',now(),%s,now(),now()),
          (2,%s,%s,%s,'Venue A',%s,1,'Supplier A',1,'received',now(),'2026-07-23',now(),%s,now(),now())""",(ORDER_A,PO_A,VENUE_A,str(uuid4()),EVENT,ORDER_B,PO_B,VENUE_A,str(uuid4()),str(uuid4())))
        for idx,(product,qty,received,unit) in enumerate([(1,5,5,'pz'),(2,5,5,'pz'),(3,5,5,'pz'),(4,2,2,'pz'),(5,1,1,'pz'),(6,1,1,'pz'),(7,1,1,'pz')],1):
          x.execute("""insert into liquidstock_supplier_order_items(id,supplier_order_id,liquidstock_supplier_order_item_id,liquidstock_product_id,product_id,product_name_snapshot,quantity,unit,package_note,ordered_quantity,received_quantity,created_at,updated_at) values (%s,1,%s,%s,%s,%s,%s,%s,%s,%s,%s,now(),now())""",(idx,ITEMS[idx-1],str(uuid4()),product,f'Product {product}',qty,unit,'6 x 1 L' if product==5 else None,qty,received))

async def run():
  seed(); token=create_access_token(1,'admin'); headers={'Authorization':f'Bearer {token}'}
  async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://testserver') as client:
    async def call(method,path,body=None): return await client.request(method,path,headers=headers,json=body)
    r=await call('POST','/api/v1/reconciliations/venue-mappings',{'liquidstock_venue_id':VENUE_A,'location_id':1}); check('venue mapping',r.status_code==200)
    r=await call('GET',f'/api/v1/reconciliations/orders/{PO_A}/invoice-candidates'); check('invoice candidates are suggestions only',r.status_code==200 and [item['id'] for item in r.json()]==[1])
    r=await call('POST',f'/api/v1/reconciliations/orders/{PO_A}/invoice',{'fattura_id':2}); check('cross venue blocked',r.status_code==409)
    r=await call('POST',f'/api/v1/reconciliations/orders/{PO_A}/invoice',{'fattura_id':3}); check('cross supplier blocked',r.status_code==409)
    r=await call('POST',f'/api/v1/reconciliations/orders/{PO_A}/invoice',{'fattura_id':1,'price_tolerance_absolute':.01,'price_tolerance_percent':1}); check('valid invoice association',r.status_code==200); rid=r.json()['id']
    r=await call('DELETE',f'/api/v1/reconciliations/{rid}/invoice'); check('manual invoice unlink',r.status_code==200 and r.json()['status']=='awaiting_invoice')
    r=await call('POST',f'/api/v1/reconciliations/orders/{PO_A}/invoice',{'fattura_id':1,'price_tolerance_absolute':.01,'price_tolerance_percent':1}); check('manual invoice relink',r.status_code==200)
    r=await call('POST',f'/api/v1/reconciliations/orders/{PO_B}/invoice',{'fattura_id':1}); check('double association blocked',r.status_code==409)
    r=await call('POST',f'/api/v1/reconciliations/orders/{PO_B}/invoice',{'fattura_id':1,'allow_reassociate':True}); check('explicit reassociation is required and supported',r.status_code==200)
    r=await call('POST',f'/api/v1/reconciliations/orders/{PO_A}/invoice',{'fattura_id':1,'allow_reassociate':True,'price_tolerance_absolute':.01,'price_tolerance_percent':1}); check('explicit reassociation can return to original order',r.status_code==200)
    r=await call('POST',f'/api/v1/reconciliations/{rid}/match'); check('matching completes',r.status_code==200); data=r.json(); statuses={i['riga_fattura_id']:i for i in data['items'] if i['riga_fattura_id']}
    check('exact product id match',statuses[1]['match_method']=='product_id')
    check('supplier alias match',statuses[2]['match_method']=='supplier_product_alias')
    check('ean match',statuses[3]['match_method']=='ean')
    check('overbilling',statuses[2]['anomaly_type']=='quantity_overbilled')
    check('underbilling',statuses[3]['anomaly_type']=='quantity_underbilled')
    check('price overcharge',statuses[4]['anomaly_type']=='price_overcharge' and statuses[4]['expected_price_source'].startswith('listino_master'))
    check('unit mismatch',statuses[5]['anomaly_type']=='unit_mismatch' and statuses[5]['quantity_delta'] is None)
    check('package note snapshot remains visible',statuses[5]['ordered_package_note']=='6 x 1 L')
    check('price tolerance',statuses[6]['match_status']=='matched')
    check('unordered item',statuses[7]['anomaly_type']=='unordered_item')
    check('fuzzy is candidate only',statuses[8]['match_status']=='ambiguous' and statuses[8]['match_method']=='candidate_only')
    check('duplicate invoice line',statuses[1]['anomaly_type']=='duplicate_invoice_line')
    check('missing invoice item',any(i['anomaly_type']=='missing_invoice_item' for i in data['items']))
    fuzzy=statuses[8]; candidate=fuzzy['candidate_evidence']['fallback_candidates'][0]
    r=await call('POST',f"/api/v1/reconciliations/{rid}/items/{fuzzy['id']}/resolve",{'action':'confirm','liquidstock_item_id':candidate['liquidstock_item_id'],'product_id':candidate['product_id']}); check('fuzzy confirmation is explicit',r.status_code==200 and any(i['id']==fuzzy['id'] and i['match_method']=='manual_confirmation' for i in r.json()['items']))
    check('confirmed candidate removes missing placeholder',sum(1 for i in r.json()['items'] if i.get('liquidstock_item_id')==candidate['liquidstock_item_id'])==1)
    duplicate=next(i for i in r.json()['items'] if i.get('anomaly_type')=='duplicate_invoice_line')
    r=await call('POST',f"/api/v1/reconciliations/{rid}/items/{duplicate['id']}/resolve",{'action':'ignore'}); check('duplicate can be reviewed',r.status_code==200)
    over=next(i for i in data['items'] if i['anomaly_type']=='quantity_overbilled')
    r=await call('POST',f"/api/v1/reconciliations/{rid}/items/{over['id']}/resolve",{'action':'create_anomaly'}); check('anomaly created',r.status_code==200 and len(r.json()['anomalies'])==1)
    r=await call('POST',f"/api/v1/reconciliations/{rid}/items/{over['id']}/resolve",{'action':'create_anomaly'}); check('anomaly idempotent',r.status_code==200 and len(r.json()['anomalies'])==1)
    payload=json.dumps({'liquidstock_supplier_order_id':PO_A},separators=(',',':')).encode(); ts=str(int(time.time())); secret=os.environ['LIQUIDSTOCK_INTEGRATION_SECRET']; sig=hmac.new(secret.encode(),ts.encode()+b'.'+payload,hashlib.sha256).hexdigest()
    h={'X-Integration-Source':'liquidstock','X-Event-Id':str(uuid4()),'X-Event-Timestamp':ts,'X-Event-Signature':sig,'Content-Type':'application/json'}
    r=await client.post('/api/v1/integrations/liquidstock/reconciliations/status',content=payload,headers={**h,'X-Event-Signature':'0'*64}); check('invalid HMAC is rejected generically',r.status_code==401 and 'integration_authentication_failed' in r.text)
    r=await client.post('/api/v1/integrations/liquidstock/reconciliations/status',content=payload,headers=h); check('signed status returned',r.status_code==200 and r.json()['reconciliation_id']==rid)
    r2=await client.post('/api/v1/integrations/liquidstock/reconciliations/status',content=payload,headers={**h,'X-Event-Id':str(uuid4())}); check('status query idempotent',r2.status_code==200 and r2.json()==r.json())
    missing_payload=json.dumps({'liquidstock_supplier_order_id':str(uuid4())},separators=(',',':')).encode(); missing_sig=hmac.new(secret.encode(),ts.encode()+b'.'+missing_payload,hashlib.sha256).hexdigest()
    r=await client.post('/api/v1/integrations/liquidstock/reconciliations/status',content=missing_payload,headers={**h,'X-Event-Id':str(uuid4()),'X-Event-Signature':missing_sig}); check('signed unknown order is reported without mutation',r.status_code==404 and r.json()['error']=='order_not_found')
    r=await call('POST',f'/api/v1/reconciliations/{rid}/close',{}); check('reconciliation closes after ambiguity review',r.status_code==200 and r.json()['status']=='closed')
    r=await call('DELETE',f'/api/v1/reconciliations/{rid}/invoice'); check('closed reconciliation immutable',r.status_code==409)
  check('legacy anomalies untouched',scalar('select count(*) from anomalie')==0)
  print(json.dumps({'status':'PASS','tests':len(results),'results':results},indent=2),flush=True)

asyncio.run(run())
