foreach(MODULE_TYPE "agent" "agentd" "server")
    add_library(python-zabbix_${MODULE_TYPE}-modules
            SHARED
                python_zabbix_modules.c)
    target_include_directories(python-zabbix_${MODULE_TYPE}-modules
            PUBLIC
                ${CMAKE_SOURCE_DIR}/include/zabbix/${ZABBIX_VERSION}
                ${PYTHON_INCLUDE_DIRS})

    set_property(TARGET python-zabbix_${MODULE_TYPE}-modules
            APPEND_STRING PROPERTY COMPILE_FLAGS
                " -g -O2 -std=c11 -pedantic -Wall -Wextra")

    set_property(TARGET python-zabbix_${MODULE_TYPE}-modules
            APPEND_STRING PROPERTY COMPILE_FLAGS
                \ -DPROJECT_NAME=\\"${PROJECT_NAME}\\")
    set_property(TARGET python-zabbix_${MODULE_TYPE}-modules
            APPEND_STRING PROPERTY COMPILE_FLAGS
                \ -DMODULE_TYPE=\\"${MODULE_TYPE}\\")
    set_property(TARGET python-zabbix_${MODULE_TYPE}-modules
            APPEND_STRING PROPERTY COMPILE_FLAGS
                \ -DPYTHON_LIB_NAME=\\"${PYTHON_LIBRARIES}\\")

    target_link_libraries(python-zabbix_${MODULE_TYPE}-modules
            LINK_PUBLIC
                ${PYTHON_LIBRARIES}
                ${CMAKE_THREAD_LIBS_INIT}
                ${CMAKE_DL_LIBS})
endforeach(MODULE_TYPE)
