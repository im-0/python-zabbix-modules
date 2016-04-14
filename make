#!/bin/sh -eu


DEFAULT_ZABBIX_VERSION=3.0.0


printHelpAndExit()
{
cat >&2 << end
Usage:
    $0 -h
    $0 [-v] [-z <zabbix version>] [-S] [-P <python version override for CMake>] [2] [3]
    $0 -c [-v]

Options:
    -h - Print this help message and exit.
    -v - Verbose.
    -z - Set version of Zabbix headers to use (default is "${DEFAULT_ZABBIX_VERSION}").
    -S - Build without syslog (module will write into stderr instead of syslog).
    -P - Set exact python version for CMake's find_package().
    -c - Clean.
end
    exit 1
}


fail()
{
    echo "${1}" >&2
    exit 1
}


opt_verbose=""
opt_clean=""
opt_zabbix="${DEFAULT_ZABBIX_VERSION}"
opt_no_syslog="0"
opt_cmake_python_override=""
while getopts "hvz:SP:c" opt; do
    case "${opt}" in
        "h") printHelpAndExit;;
        "v") opt_verbose="y";;
        "z") opt_zabbix="${OPTARG}";;
        "S") opt_no_syslog="1";;
        "c") opt_clean="y";;
        "P") opt_cmake_python_override="${OPTARG}";;
        *)   printHelpAndExit;;
    esac
done

[ -n "${opt_verbose}" ] && set -x

if [ -n "${opt_clean}" ]; then
    rm -frv "./build"
    exit 0
fi

shift $(( $OPTIND - 1 ))
if [ $# -eq 0 ]; then
    versions="2 3"
else
    versions="${@}"
fi

[ -e "./make" -a -e "./CMakeLists.txt" ] || fail "Wrong directory"

for version in $versions; do
    mkdir -p "./build/py${version}/zabbix-${opt_zabbix}"
    cd "./build/py${version}/zabbix-${opt_zabbix}"
    if [ -n "${opt_verbose}" ]; then
        cmake \
                -DCMAKE_VERBOSE_MAKEFILE=ON \
                -DPYTHON_VERSION=${version} \
                -DZABBIX_VERSION=${opt_zabbix} \
                -DNO_SYSLOG=${opt_no_syslog} \
                -DPYTHON_VERSION_OVERRIDE=${opt_cmake_python_override} \
                "../../.."
    else
        cmake \
                -DPYTHON_VERSION=${version} \
                -DZABBIX_VERSION=${opt_zabbix} \
                -DNO_SYSLOG=${opt_no_syslog} \
                -DPYTHON_VERSION_OVERRIDE=${opt_cmake_python_override} \
                "../../.."
    fi
    make
    cd "../../.."
done

for version in $versions; do
    ls -lh "./build/py${version}/zabbix-${opt_zabbix}/src"/*.so
done
