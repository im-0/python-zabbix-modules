cmake_minimum_required (VERSION 2.8.0)
project(python-zabbix-modules)

if(NOT DEFINED PYTHON_VERSION)
    message(FATAL_ERROR "Set PYTHON_VERSION to either 2 or 3")
endif(NOT DEFINED PYTHON_VERSION)
if(NOT DEFINED ZABBIX_VERSION)
    message(FATAL_ERROR "Set ZABBIX_VERSION to use appropriate headers from ./include/zabbix/")
endif(NOT DEFINED ZABBIX_VERSION)
find_package(PythonLibs ${PYTHON_VERSION} REQUIRED)

find_package(Threads REQUIRED)

add_subdirectory(src)
