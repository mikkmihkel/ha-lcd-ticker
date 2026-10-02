# Security policy

## Reporting a vulnerability

Please report vulnerabilities privately. On the repository page, open the **Security**
tab and choose **Report a vulnerability** (GitHub private vulnerability reporting). Do not
open a public issue for a security problem.

## Supported versions

Only the latest release is supported.

## Scope

LCD Ticker has no runtime dependencies beyond Home Assistant core and makes no network
connections. It only uses local Bluetooth through Home Assistant. Diagnostics redact the
MAC address.

The pvvx firmware on the thermometer is third-party software and is outside this
project. Report firmware issues to [pvvx/ATC_MiThermometer](https://github.com/pvvx/ATC_MiThermometer).
