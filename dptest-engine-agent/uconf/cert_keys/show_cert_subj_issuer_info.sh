#!/bin/bash

DIR="${1:-.}"

find "$DIR" -type f -name "*.crt" | while read -r crt; do
    echo "=============================="
    echo "文件: $crt"

    subject=$(openssl x509 -in "$crt" -noout -subject 2>/dev/null)
    issuer=$(openssl x509 -in "$crt" -noout -issuer 2>/dev/null)

    if [ $? -ne 0 ]; then
        echo "读取失败: $crt 不是有效证书，或格式不受支持"
    else
        echo "$subject"
        echo "$issuer"
    fi
    echo
done
