from __future__ import annotations

import base64
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.domain.qnb_earsiv import (  # noqa: E402
    QnbEarsivCredentials,
    QnbSoapEarsivAdapter,
    is_qnb_earsiv_test_endpoint,
    qnb_earsiv_credentials_from_env,
)


class FakeSoapResponse:
    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSoapHttpClient:
    def __init__(self, responses: list[str | tuple[str, int]]) -> None:
        self.responses = list(responses)
        self.requests: list[dict[str, object]] = []

    def post(self, url: str, *, content: str, headers: dict[str, str], timeout: int) -> FakeSoapResponse:
        self.requests.append({"url": url, "content": content, "headers": headers, "timeout": timeout})
        response = self.responses.pop(0)
        if isinstance(response, tuple):
            return FakeSoapResponse(response[0], response[1])
        return FakeSoapResponse(response)


def soap_body(inner: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
        f"<soap:Body>{inner}</soap:Body></soap:Envelope>"
    )


def credentials() -> QnbEarsivCredentials:
    return QnbEarsivCredentials(
        user_service_url="https://connectortest.qnbesolutions.com.tr/connector/ws/userService",
        service_url="https://earsivtest.qnbesolutions.com.tr/earsiv/ws",
        username="5910611340.portaltest",
        password="secret-password",
        vkn="5910611340",
        erp_code="FSR31422",
    )


class QnbEarsivTests(unittest.TestCase):
    def test_connection_maps_portal_verification_fault(self) -> None:
        client = FakeSoapHttpClient(
            [
                (
                    soap_body(
                        '<soap:Fault xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
                        "<faultstring>[EF0556] Mali mühür veya e-imza doğrulaması gereklidir.</faultstring>"
                        "</soap:Fault>"
                    ),
                    500,
                )
            ]
        )
        result = QnbSoapEarsivAdapter(http_client=client).test_connection(credentials())

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "portal_verification_required")
        self.assertNotIn("secret-password", result.message)

    def test_create_invoice_uses_ext_json_erp_code_and_base64_ubl(self) -> None:
        pdf = b"%PDF-1.7\nqnb-test"
        response = soap_body(
            f"""
<ns2:faturaOlusturExtResponse xmlns:ns2="http://service.earsiv.uut.cs.com.tr/">
  <output><belgeFormati>PDF</belgeFormati><belgeIcerigi>{base64.b64encode(pdf).decode('ascii')}</belgeIcerigi></output>
  <return>
    <resultCode>AE00000</resultCode>
    <resultExtra>
      <entry><key>islemID</key><value>uuid-1</value></entry>
      <entry><key>uuid</key><value>uuid-1</value></entry>
      <entry><key>faturaNo</key><value>EAR2026000000001</value></entry>
      <entry><key>faturaURL</key><value>https://example.test/invoice</value></entry>
    </resultExtra>
    <resultText>İşlem başarılı.</resultText>
  </return>
</ns2:faturaOlusturExtResponse>
"""
        )
        client = FakeSoapHttpClient(
            [soap_body('<ns2:wsLoginResponse xmlns:ns2="http://service.csap.cs.com.tr/"/>'), response]
        )
        adapter = QnbSoapEarsivAdapter(http_client=client)
        ubl = b'<?xml version="1.0"?><Invoice>test</Invoice>'

        result = adapter.create_invoice_ubl(
            credentials(),
            transaction_id="uuid-1",
            content=ubl,
            assign_invoice_number=True,
            invoice_series="EAR",
            send_to_draft=False,
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.invoice_no, "EAR2026000000001")
        self.assertEqual(result.invoice_uuid, "uuid-1")
        self.assertEqual(result.output_format, "PDF")
        self.assertEqual(result.output_content, pdf)
        request = str(client.requests[1]["content"])
        self.assertIn("<qnb:faturaOlusturExt", request)
        self.assertIn("<belgeFormati>UBL</belgeFormati>", request)
        self.assertIn(base64.b64encode(ubl).decode("ascii"), request)
        input_start = request.index("<input>") + len("<input>")
        input_end = request.index("</input>")
        payload = json.loads(request[input_start:input_end].replace("&quot;", '"'))
        self.assertEqual(payload["erpKodu"], "FSR31422")
        self.assertEqual(payload["sube"], "DFLT")
        self.assertEqual(payload["kasa"], "DFLT")
        self.assertEqual(payload["numaraVerilsinMi"], 1)
        self.assertEqual(payload["faturaSeri"], "EAR")
        self.assertEqual(payload["taslagaYonlendir"], 0)

    def test_env_mapping_and_test_endpoint_guard(self) -> None:
        mapped = qnb_earsiv_credentials_from_env(
            {
                "QNB_EARSIV_USER_SERVICE_URL": "https://connectortest.qnbesolutions.com.tr/connector/ws/userService",
                "QNB_EARSIV_TEST_BASE_URL": "https://earsivtest.qnbesolutions.com.tr/earsiv/ws",
                "QNB_EARSIV_TEST_USERNAME": "portal-user",
                "QNB_EARSIV_TEST_PASSWORD": "secret",
                "QNB_EARSIV_TEST_VKN": "5910611340",
                "QNB_ERP_CODE": "FSR31422",
            }
        )

        self.assertEqual(mapped.erp_code, "FSR31422")
        self.assertEqual(mapped.vkn, "5910611340")
        self.assertTrue(is_qnb_earsiv_test_endpoint(mapped.user_service_url))
        self.assertTrue(is_qnb_earsiv_test_endpoint(mapped.service_url))
        self.assertFalse(is_qnb_earsiv_test_endpoint("https://earsiv.qnbesolutions.com.tr/earsiv/ws"))
        self.assertFalse(
            is_qnb_earsiv_test_endpoint("https://evil.example/earsivtest.qnbesolutions.com.tr/earsiv/ws")
        )

    def test_create_invoice_rejects_production_endpoint_before_network(self) -> None:
        client = FakeSoapHttpClient([])
        production = QnbEarsivCredentials(
            user_service_url="https://connector.qnbesolutions.com.tr/connector/ws/userService",
            service_url="https://earsiv.qnbesolutions.com.tr/earsiv/ws",
            username="portal-user",
            password="secret-password",
            vkn="5910611340",
            erp_code="FSR31422",
        )

        with self.assertRaisesRegex(ValueError, "test endpoint"):
            QnbSoapEarsivAdapter(http_client=client).create_invoice_ubl(
                production,
                transaction_id="uuid-1",
                content=b'<?xml version="1.0"?><Invoice>test</Invoice>',
            )

        self.assertEqual(client.requests, [])

    def test_create_invoice_rejects_unsuccessful_result_code(self) -> None:
        response = soap_body(
            """
<ns2:faturaOlusturExtResponse xmlns:ns2="http://service.earsiv.uut.cs.com.tr/">
  <return><resultCode>AE99999</resultCode><resultText>Reddedildi</resultText></return>
</ns2:faturaOlusturExtResponse>
"""
        )
        client = FakeSoapHttpClient(
            [soap_body('<ns2:wsLoginResponse xmlns:ns2="http://service.csap.cs.com.tr/"/>'), response]
        )

        with self.assertRaisesRegex(ValueError, "AE99999.*Reddedildi"):
            QnbSoapEarsivAdapter(http_client=client).create_invoice_ubl(
                credentials(),
                transaction_id="uuid-1",
                content=b'<?xml version="1.0"?><Invoice>test</Invoice>',
            )

    def test_query_invoice_uses_provider_invoice_number(self) -> None:
        response = soap_body(
            """
<ns2:faturaSorgulaExtResponse xmlns:ns2="http://service.earsiv.uut.cs.com.tr/">
  <return>
    <resultCode>AE00000</resultCode>
    <resultExtra>
      <entry><key>uuid</key><value>uuid-1</value></entry>
      <entry><key>faturaNo</key><value>EAR2026000000001</value></entry>
    </resultExtra>
    <resultText>Bulundu</resultText>
  </return>
</ns2:faturaSorgulaExtResponse>
"""
        )
        client = FakeSoapHttpClient(
            [soap_body('<ns2:wsLoginResponse xmlns:ns2="http://service.csap.cs.com.tr/"/>'), response]
        )

        result = QnbSoapEarsivAdapter(http_client=client).query_invoice(
            credentials(), invoice_no="EAR2026000000001"
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.invoice_uuid, "uuid-1")
        request = str(client.requests[1]["content"])
        self.assertIn("<qnb:faturaSorgulaExt", request)
        input_start = request.index("<input>") + len("<input>")
        input_end = request.index("</input>")
        payload = json.loads(request[input_start:input_end].replace("&quot;", '"'))
        self.assertEqual(payload["faturaNo"], "EAR2026000000001")
        self.assertNotIn("islemId", payload)
        self.assertEqual(payload["vkn"], "5910611340")
        self.assertEqual(payload["erpKodu"], "FSR31422")


if __name__ == "__main__":
    unittest.main()
