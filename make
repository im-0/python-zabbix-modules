#!/bin/sh -eu


printHelpAndExit()
{
cat >&2 << end
Usage:
    $0 -h
    $0 [-v] [2] [3]
    $0 -c [-v]

Options:
    -h - Print this help message and exit.
    -v - Verbose.
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
while getopts hvc opt; do
    case "${opt}" in
        "h") printHelpAndExit;;
        "v") opt_verbose="y";;
        "c") opt_clean="y";;
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
    mkdir -p "./build/${version}"
    cd "./build/${version}"
    if [ -n "${opt_verbose}" ]; then
        cmake -DCMAKE_VERBOSE_MAKEFILE=ON -DPYTHON_VERSION=${version} "../.."
    else
        cmake -DPYTHON_VERSION=${version} "../.."
    fi
    make
    cd "../.."
done

for version in $versions; do
    ls -lh "./build/${version}/src"/*.so
done
