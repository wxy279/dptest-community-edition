#!/bin/bash

DIR="${1:-.}"

find "$DIR" -type f -name "*.crt" | while read -r crt; do
    echo "=============================="
    echo "File: $crt"

    subject=$(openssl x509 -in "$crt" -noout -subject 2>/dev/null)
    issuer=$(openssl x509 -in "$crt" -noout -issuer 2>/dev/null)

    if [ $? -ne 0 ]; then
        echo "Read failed: $crt is not a valid certificate, or the format is not supported"
    else
        echo "$subject"
        echo "$issuer"
    fi
    echo
done
