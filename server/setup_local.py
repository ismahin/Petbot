"""Create private TLS/auth configuration for the local XIAO connection."""
import argparse
from datetime import datetime, timedelta, timezone
import ipaddress
import json
from pathlib import Path
import secrets
import time
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

ROOT = Path(__file__).resolve().parent
PRIVATE = ROOT / "private"

def pem_key(key):
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption())

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--device-mac", required=True)
    parser.add_argument("--port", type=int, default=8443)
    parser.add_argument("--renew-cert", action="store_true")
    args = parser.parse_args()
    address = ipaddress.ip_address(args.host)
    if not address.is_private or address.is_loopback:
        parser.error("Use the PC's LAN address")
    PRIVATE.mkdir(exist_ok=True)
    path = PRIVATE / "config.json"
    config = json.loads((ROOT / "config.example.json").read_text())
    if path.exists():
        config.update(json.loads(path.read_text()))
    config.update(host=args.host, port=args.port, allowed_device_mac=args.device_mac.lower())
    config.setdefault("device_token", secrets.token_urlsafe(32))
    cert_path = PRIVATE / "server.crt"
    regenerate = args.renew_cert or not cert_path.exists()
    if cert_path.exists():
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        regenerate = regenerate or address not in cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.IPAddress)
    if regenerate:
        now = datetime.now(timezone.utc)
        ca_key = ec.generate_private_key(ec.SECP256R1())
        ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Deskter Local CA")])
        ca = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name)
              .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
              .not_valid_before(now-timedelta(days=1)).not_valid_after(now+timedelta(days=1095))
              .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
              .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
              .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
              .add_extension(x509.KeyUsage(False,False,False,False,False,True,True,False,False), critical=True)
              .sign(ca_key, hashes.SHA256()))
        server_key = ec.generate_private_key(ec.SECP256R1())
        server_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Deskter Local Server")])
        cert = (x509.CertificateBuilder().subject_name(server_name).issuer_name(ca_name)
                .public_key(server_key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now-timedelta(days=1)).not_valid_after(now+timedelta(days=1095))
                .add_extension(x509.SubjectAlternativeName([x509.IPAddress(address)]), critical=False)
                .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                .add_extension(x509.SubjectKeyIdentifier.from_public_key(server_key.public_key()), critical=False)
                .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
                .add_extension(x509.KeyUsage(True,False,False,False,False,False,False,False,False), critical=True)
                .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
                .sign(ca_key, hashes.SHA256()))
        (PRIVATE / "ca.key").write_bytes(pem_key(ca_key))
        (PRIVATE / "ca.crt").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
        (PRIVATE / "server.key").write_bytes(pem_key(server_key))
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    request = {"cmd":"server", "url":f"https://{args.host}:{args.port}/xiaozhi/ota/",
               "ca":(PRIVATE / "ca.crt").read_text(), "token":config["device_token"],
               "ntp":args.host, "utc":int(time.time())}
    (PRIVATE / "provision.json").write_text(json.dumps(request), encoding="utf-8")
    print(f"Private configuration ready for {args.host}:{args.port}; credentials not printed.")

if __name__ == "__main__":
    main()
