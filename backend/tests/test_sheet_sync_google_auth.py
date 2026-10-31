"""Keyless Google Sheets auth tests; no Google Cloud access or credentials needed."""
from unittest import TestCase
from unittest.mock import MagicMock, patch

from app.services.sheet_sync_google import GoogleSheetsReadOnly, READONLY_SCOPE


class GoogleSheetsCredentialTests(TestCase):
    def test_uses_google_application_default_credentials(self):
        credentials = MagicMock()
        with patch("google.auth.default", return_value=(credentials, "test-project")) as default:
            connector = GoogleSheetsReadOnly("1klQw-Ps7reJHu2Hii3T9GltpfbK7PQrnpalfFFygtGM")
        self.assertIs(connector._credentials, credentials)
        default.assert_called_once_with(scopes=[READONLY_SCOPE])

    def test_passed_credentials_do_not_trigger_cloud_auth(self):
        fake_creds = MagicMock()
        with patch("google.auth.default") as default:
            connector = GoogleSheetsReadOnly(
                "1klQw-Ps7reJHu2Hii3T9GltpfbK7PQrnpalfFFygtGM",
                credentials=fake_creds,
            )
        default.assert_not_called()
        self.assertIs(connector._credentials, fake_creds)

    def test_invalid_spreadsheet_id_rejected_before_auth(self):
        with patch("google.auth.default") as default:
            with self.assertRaises(ValueError):
                GoogleSheetsReadOnly("https://evil.example/")
        default.assert_not_called()
