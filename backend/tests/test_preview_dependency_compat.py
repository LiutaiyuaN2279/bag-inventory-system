"""Normal, bounded dependency compatibility checks; no exploit payloads or AI calls.

Run with a NEW PREVIEW_TEST_ROOT and explicit demo settings before importing app.
This separate process may write only synthetic files/data; it is not a core test.
"""
import base64
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

class DependencyCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(os.environ['PREVIEW_TEST_ROOT']).resolve()
        assert cls.root.is_dir()
        from app.core.config import settings
        cls.settings = settings
        db = Path(settings.DATABASE_URL.removeprefix('sqlite:///')).resolve()
        assert db.is_relative_to(cls.root) and not db.exists(), 'require a fresh synthetic database'
        assert Path(settings.UPLOAD_DIR).resolve().is_relative_to(cls.root)
        assert settings.AI_OCR_PROVIDER == 'mock' and not settings.GITHUB_OAUTH_ENABLED
        assert not settings.AI_OCR_API_KEY and not settings.GITHUB_CLIENT_SECRET
        from scripts.init_db import init
        init()  # New synthetic schema only; no existing database or migration.
        from app.main import app
        from fastapi.testclient import TestClient
        cls.client = TestClient(app)
        cls.client.__enter__()
        response = cls.client.post('/api/v1/auth/login', json={'username':'admin','password':'admin123'})
        assert response.status_code == 200 and response.json()['code'] == 0
        cls.headers = {'Authorization':'Bearer ' + response.json()['data']['access_token']}

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        from app.core.database import engine
        engine.dispose()

    @staticmethod
    def pdf_bytes(text=True):
        from pypdf import PdfWriter
        from pypdf.generic import NameObject, DictionaryObject, DecodedStreamObject
        writer = PdfWriter()
        page = writer.add_blank_page(width=72, height=72)
        if text:
            font = DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
            page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
            stream = DecodedStreamObject(); stream.set_data(b'BT /F1 10 Tf 4 40 Td (Synthetic preview invoice) Tj ET')
            page[NameObject('/Contents')] = writer._add_object(stream)
        out = io.BytesIO(); writer.write(out); return out.getvalue()

    def test_versions_and_fastapi_starlette_constraints(self):
        from importlib.metadata import version, requires
        self.assertEqual(version('fastapi'), '0.162.0')
        self.assertEqual(version('starlette'), '1.10.0')
        self.assertEqual(version('pypdf'), '6.21.4')
        self.assertIn('starlette>=0.46.0', requires('fastapi'))

    def test_actual_health_login_and_input_validation(self):
        response = self.client.get('/api/health')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['code'], 0)
        me = self.client.get('/api/v1/auth/userinfo', headers=self.headers)
        self.assertEqual(me.json()['code'], 0)
        bad = self.client.post('/api/v1/auth/login', json={'username':[],'password':{}})
        self.assertNotEqual(bad.json().get('code'), 0)

    def test_actual_mock_upload_file_response_and_small_range(self):
        image = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a/A8AAAAASUVORK5CYII=')
        response = self.client.post('/api/v1/ai-ocr/recognize', headers=self.headers,
                                    files={'file':('synthetic.png',image,'image/png')})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['code'],0)
        record = response.json()['data']; self.assertEqual(record['provider'],'mock')
        self.assertTrue(record['has_image'])
        full = self.client.get(record['image_url'],headers=self.headers)
        self.assertEqual(full.status_code,200); self.assertEqual(full.content,image)
        part = self.client.get(record['image_url'],headers=self.headers | {'Range':'bytes=0-7'})
        self.assertEqual(part.status_code,206); self.assertEqual(part.content,image[:8])
        self.assertEqual(part.headers['content-range'],f'bytes 0-7/{len(image)}')
        invalid = self.client.get(record['image_url'],headers=self.headers | {'Range':f'bytes={len(image)+5}-'})
        self.assertEqual(invalid.status_code,416)

    def test_static_files_full_head_and_small_range(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from starlette.staticfiles import StaticFiles
        with tempfile.TemporaryDirectory(dir=self.root) as d:
            data=b'0123456789synthetic';(Path(d)/'sample.txt').write_bytes(data)
            app=FastAPI();app.mount('/files',StaticFiles(directory=d))
            with TestClient(app) as client:
                self.assertEqual(client.get('/files/sample.txt').content,data)
                self.assertEqual(client.head('/files/sample.txt').status_code,200)
                response=client.get('/files/sample.txt',headers={'Range':'bytes=2-5'})
                self.assertEqual(response.status_code,206);self.assertEqual(response.content,b'2345')

    def test_multipart_small_and_normal_disk_spooled_uploads(self):
        from fastapi import FastAPI, UploadFile, File
        from fastapi.testclient import TestClient
        app=FastAPI()
        @app.post('/upload')
        async def upload(file:UploadFile=File(...)):
            content=await file.read()
            return {'size':len(content),'rolled':bool(getattr(file.file,'_rolled',False))}
        with TestClient(app) as client:
            for size in (64, 1024*1024+64):  # One normal spool rollover, bounded <1.1 MiB.
                with self.subTest(size=size):
                    response=client.post('/upload',files={'file':('synthetic.bin',b'x'*size,'application/octet-stream')})
                    self.assertEqual(response.status_code,200)
                    self.assertEqual(response.json()['size'],size)
                    self.assertEqual(response.json()['rolled'],size>1024*1024)

    def test_pypdf_and_actual_invoice_text_reader(self):
        from pypdf import PdfReader
        from app.services.invoice_ai import pdf_extract_text
        data=self.pdf_bytes()
        self.assertEqual(len(PdfReader(io.BytesIO(data)).pages),1)
        self.assertIn('Synthetic preview invoice',pdf_extract_text(data))
        self.assertEqual(pdf_extract_text(self.pdf_bytes(text=False)),'')

    def test_pdf_render_synthetic_blank_one_page(self):
        from app.services.invoice_ai import pdf_render_png
        data,mime=pdf_render_png(self.pdf_bytes(text=False),scale=1)
        self.assertEqual(mime,'image/png');self.assertTrue(data.startswith(b'\x89PNG\r\n\x1a\n'))
        self.assertLess(len(data),100000)

    def test_real_pdf_upload_uses_mock_not_external_source(self):
        from app.services import invoice_ai
        def local_pdf(data,filename='',mime='',**kwargs):
            return {'recognize_mode':'pdf_text','raw_text':invoice_ai.pdf_extract_text(data),'model':'synthetic-local-stub','items':[]}
        data=self.pdf_bytes()
        with patch.object(invoice_ai,'recognize_invoice',side_effect=local_pdf) as call:
            response=self.client.post('/api/v1/rmb-bills/recognize',headers=self.headers,
                files={'file':('synthetic.pdf',data,'application/pdf')})
        self.assertEqual(response.status_code,200);self.assertEqual(response.json()['code'],0)
        self.assertEqual(call.call_count,1)
        self.assertEqual(call.call_args.args,(data,'synthetic.pdf','application/pdf'))
        result=response.json()['data']
        self.assertTrue(result['recognize_ok']);self.assertTrue(result['has_file'])
        self.assertEqual(result['recognize_mode'],'pdf_text')
        self.assertEqual(result['model'],'synthetic-local-stub')
        self.assertEqual(result['original_filename'],'synthetic.pdf')
        from hashlib import sha256
        self.assertEqual(result['file_hash'],sha256(data).hexdigest())

    def test_approved_batch2_dependency_versions(self):
        from importlib.metadata import version
        self.assertEqual(version('python-multipart'),'0.0.31')
        self.assertEqual(version('PyJWT'),'2.15.0')
        self.assertGreaterEqual(len(self.settings.SECRET_KEY.encode('utf-8')),32)

    def test_form_urlencoded_empty_repeated_and_separators(self):
        # WHATWG URL form convention: '&' separates; ';' is data. No duplicate-ID business policy.
        from fastapi import FastAPI, Request
        from fastapi.testclient import TestClient
        app=FastAPI()
        @app.post('/form')
        async def form(request:Request):
            value=await request.form()
            return {'pairs':list(value.multi_items()),'tags':value.getlist('tag')}
        cases=[('empty=&tag=one&tag=two',[['empty',''],['tag','one'],['tag','two']],['one','two']),
               ('tag=one;admin=true',[['tag','one;admin=true']],['one;admin=true']),
               ('tag=a%3Bb%26c&tag=',[['tag','a;b&c'],['tag','']],['a;b&c',''])]
        with TestClient(app) as client:
            for body,pairs,tags in cases:
                with self.subTest(body=body):
                    response=client.post('/form',content=body,headers={'Content-Type':'application/x-www-form-urlencoded'})
                    self.assertEqual(response.status_code,200)
                    self.assertEqual(response.json(),{'pairs':pairs,'tags':tags})

    def test_form_multipart_preserves_empty_and_repeated_fields(self):
        # Starlette FormData is a multidict: keep empty values and every occurrence in order.
        from fastapi import FastAPI, Request
        from fastapi.testclient import TestClient
        app=FastAPI()
        @app.post('/form')
        async def form(request:Request):
            value=await request.form()
            return {'pairs':list(value.multi_items()),'tags':value.getlist('tag')}
        with TestClient(app) as client:
            response=client.post('/form',files=[('empty',(None,'')),('tag',(None,'one')),('tag',(None,'two;three'))])
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json(),{'pairs':[['empty',''],['tag','one'],['tag','two;three']],'tags':['one','two;three']})

    def test_actual_invoice_optional_empty_form_fields(self):
        # Existing route documents optional empty strings as missing, not numeric conversion errors.
        from app.services import invoice_ai
        result={'recognize_mode':'pdf_text','model':'synthetic-local-stub','items':[]}
        with patch.object(invoice_ai,'recognize_invoice',return_value=result) as call:
            response=self.client.post('/api/v1/rmb-bills/recognize',headers=self.headers,
                data={'employee_id':'','expense_type_id':'','occur_date':'','amount':'','has_invoice':''},
                files={'file':('empty-options.pdf',self.pdf_bytes(),'application/pdf')})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['code'],0)
        self.assertTrue(response.json()['data']['recognize_ok'])
        self.assertTrue(response.json()['data']['has_file'])
        self.assertEqual(call.call_count,1)

    def test_jwt_library_and_application_authentication(self):
        import jwt
        import base64
        from datetime import datetime,timedelta,timezone
        from app.core.security import create_access_token,decode_token
        from app.core.exceptions import CODE_UNAUTHORIZED
        valid=create_access_token(1)
        payload={'sub':'1','exp':datetime.now(timezone.utc)+timedelta(minutes=5)}
        expired=jwt.encode(payload|{'exp':datetime.now(timezone.utc)-timedelta(minutes=2)},self.settings.SECRET_KEY,algorithm='HS256')
        parts=valid.split('.')
        signature=bytearray(base64.urlsafe_b64decode(parts[2]+'='*(-len(parts[2])%4)))
        signature[0]^=1
        tampered='.'.join(parts[:2]+[base64.urlsafe_b64encode(signature).rstrip(b'=').decode('ascii')])
        disallowed=jwt.encode(payload,self.settings.SECRET_KEY,algorithm='HS512')
        cases=[('valid',valid,None),('expired',expired,jwt.ExpiredSignatureError),
               ('tampered',tampered,jwt.InvalidSignatureError),('malformed','not-a-jwt',jwt.DecodeError),
               ('disallowed_algorithm',disallowed,jwt.InvalidAlgorithmError)]
        for name,token,error in cases:
            with self.subTest(kind=name):
                if error is None:self.assertEqual(decode_token(token)['sub'],'1')
                else:
                    with self.assertRaises(error):decode_token(token)
                response=self.client.get('/api/v1/auth/userinfo',headers={'Authorization':'Bearer '+token})
                self.assertEqual(response.status_code,200)  # Existing business-error envelope; not HTTP 500.
                self.assertEqual(response.json()['code'],0 if error is None else CODE_UNAUTHORIZED)
                if error is None:self.assertEqual(response.json()['data']['username'],'admin')
                else:self.assertIsNone(response.json()['data'])

if __name__=='__main__':
    unittest.main(verbosity=2)
