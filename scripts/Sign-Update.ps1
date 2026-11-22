param([Parameter(Mandatory)][string]$PublicCert)
$ErrorActionPreference='Stop'
# 证书只作固定公钥容器，不依赖公共 CA。按仓内证书定位私钥，禁止自动生成替代密钥。
$public=[Security.Cryptography.X509Certificates.X509Certificate2]::new($PublicCert)
$store=[Security.Cryptography.X509Certificates.X509Store]::new("My","CurrentUser")
$store.Open("ReadOnly")
$signer=$store.Certificates.Find("FindByThumbprint",$public.Thumbprint,$false) | Select-Object -First 1
if (!$signer -or !$signer.HasPrivateKey) { throw "当前 Windows 用户没有对应的发行签名私钥" }
$key=[Security.Cryptography.X509Certificates.RSACertificateExtensions]::GetRSAPrivateKey($signer)
try {
    $bytes=[Convert]::FromBase64String([Console]::In.ReadLine())
    [Convert]::ToBase64String($key.SignData($bytes,[Security.Cryptography.HashAlgorithmName]::SHA256,[Security.Cryptography.RSASignaturePadding]::Pkcs1))
} finally { $key.Dispose(); $store.Close() }
