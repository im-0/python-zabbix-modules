#if !defined(_POSIX_C_SOURCE)
#define _POSIX_C_SOURCE 200809L
#elif _POSIX_C_SOURCE < 200809L
#undef _POSIX_C_SOURCE
#define _POSIX_C_SOURCE 200809L
#endif

#include <stdint.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>

#include <syslog.h>

#include <dlfcn.h>
#include <pthread.h>
#include <sys/types.h>
#include <unistd.h>

#include <Python.h>

/* zabbix/module.h */
#include "module.h"


#define log(priority, ...) syslog(priority, "[" PROJECT_NAME "] " __VA_ARGS__)


#if PY_MAJOR_VERSION >= 3
static wchar_t *const program_name = L"" PROJECT_NAME;
#else
static char *const program_name = PROJECT_NAME;
#endif


static bool forked_parent = false;
static bool forked_child = false;
static bool on_python_exception = false;


static ZBX_METRIC *item_list = NULL;


static const char *const item_attr_key = "key";
static const char *const item_attr_flags = "flags";
static const char *const item_attr_test_param = "test_param";

static const char *const result_attr_ui64 = "ui64";
static const char *const result_attr_dbl = "dbl";
static const char *const result_attr_str = "str";
static const char *const result_attr_text = "text";
static const char *const result_attr_msg = "msg";


typedef struct
{
    PyObject *(*fn)(PyObject *, const char *);
    PyObject **py_parent_ptr;
    const char *name;
    PyObject **py_ptr;
} ObjectNames;

typedef struct
{
    const char *const name;
    int value;
} ModuleConstantNames;


#if defined(PYTHON_LIB_NAME)
static void *python_lib_handle = NULL;
#endif


static struct {
    PyObject *traceback;
    PyObject *zabbix;
} mod = {0};

static struct {
    PyObject *format_exception_fn;
} mod_traceback = {0};

static struct {
    PyObject *request_type;
    PyObject *result_type;

    PyObject *init_fn;
    PyObject *after_fork_fn;
    PyObject *item_list_fn;
    PyObject *get_value_fn;
    PyObject *uninit_fn;
} mod_zabbix = {0};


static PyObject *get_py_mod(PyObject *, const char *name);
static PyObject *get_py_type(PyObject *py_module, const char *name);
static PyObject *get_py_fn(PyObject *py_module, const char *name);

static const ObjectNames object_names[] = {
    {
        .fn            = get_py_mod,
        .py_parent_ptr = NULL,
        .name          = "traceback",
        .py_ptr        = &mod.traceback,
    }, {
        .fn            = get_py_fn,
        .py_parent_ptr = &mod.traceback,
        .name          = "format_exception",
        .py_ptr        = &mod_traceback.format_exception_fn,
    }, {
        .fn            = get_py_mod,
        .py_parent_ptr = NULL,
        .name          = "zabbix_modules.wrapper",
        .py_ptr        = &mod.zabbix,
    }, {
        .fn            = get_py_type,
        .py_parent_ptr = &mod.zabbix,
        .name          = "AgentRequest",
        .py_ptr        = &mod_zabbix.request_type,
    }, {
        .fn            = get_py_type,
        .py_parent_ptr = &mod.zabbix,
        .name          = "AgentResult",
        .py_ptr        = &mod_zabbix.result_type,
    }, {
        .fn            = get_py_fn,
        .py_parent_ptr = &mod.zabbix,
        .name          = "init",
        .py_ptr        = &mod_zabbix.init_fn,
    }, {
        .fn            = get_py_fn,
        .py_parent_ptr = &mod.zabbix,
        .name          = "after_fork",
        .py_ptr        = &mod_zabbix.after_fork_fn,
    }, {
        .fn            = get_py_fn,
        .py_parent_ptr = &mod.zabbix,
        .name          = "item_list",
        .py_ptr        = &mod_zabbix.item_list_fn,
    }, {
        .fn            = get_py_fn,
        .py_parent_ptr = &mod.zabbix,
        .name          = "get_value",
        .py_ptr        = &mod_zabbix.get_value_fn,
    }, {
        .fn            = get_py_fn,
        .py_parent_ptr = &mod.zabbix,
        .name          = "uninit",
        .py_ptr        = &mod_zabbix.uninit_fn,
    }, {
        NULL, NULL, NULL, NULL
    },
};


static const ModuleConstantNames module_constant_names[] = {
    {"ZBX_MODULE_OK",    ZBX_MODULE_OK},
    {"ZBX_MODULE_FAIL",  ZBX_MODULE_FAIL},
    {"CF_HAVEPARAMS",    CF_HAVEPARAMS},
    {"SYSINFO_RET_OK",   SYSINFO_RET_OK},
    {"SYSINFO_RET_FAIL", SYSINFO_RET_FAIL},
    {NULL, 0},
};


static void log_python_exception();


int zbx_module_api_version()
{
    return ZBX_MODULE_API_VERSION_ONE;
}


static void after_fork_parent()
{
    forked_parent = true;
}


static void after_fork_child()
{
    forked_child = true;
    forked_parent = false;
}


static bool set_after_fork_handler()
{
    if (pthread_atfork(NULL, after_fork_parent, after_fork_child)) {
        log(LOG_ERR, "pthread_atfork() failed");
        return false;
    }
    return true;
}


static PyObject *get_py_mod(PyObject *not_used, const char *name)
{
    (void) not_used;

    PyObject *py_module = NULL;

    PyObject *py_name = PyUnicode_FromString(name);
    if (!py_name) {
        log(LOG_ERR, "Unable to load %s: PyUnicode_FromString() failed",
                name);
        goto on_error;
    }

    py_module = PyImport_Import(py_name);
    if (!py_module) {
        log(LOG_ERR, "Unable to load %s: PyImport_Import() failed",
                name);
        goto on_error;
    }

on_exit:
    Py_XDECREF(py_name);
    return py_module;

on_error:
    log_python_exception();
    Py_CLEAR(py_module);
    goto on_exit;
}


static PyObject *get_py_attr(PyObject *py_obj, const char *name)
{
    PyObject *py_attr = PyObject_GetAttrString(py_obj, name);
    if (!py_attr) {
        log(LOG_ERR,
                "Unable to get object attribute '%s': "
                "PyObject_GetAttrString() failed",
                name);
        log_python_exception();
        return NULL;
    }
    return py_attr;
}


static PyObject *get_py_type(PyObject *py_module, const char *name)
{
    PyObject *py_type = get_py_attr(py_module, name);
    if (!py_type) {
        goto on_error;
    }
    if (!PyType_Check(py_type)) {
        log(LOG_ERR, "Unable to get type %s: object is not a type",
                name);
        goto on_error;
    }

on_exit:
    return py_type;

on_error:
    log_python_exception();
    Py_CLEAR(py_type);
    goto on_exit;
}


static PyObject *get_py_fn(PyObject *py_module, const char *name)
{
    PyObject *py_fn = get_py_attr(py_module, name);
    if (!py_fn) {
        goto on_error;
    }
    if (!PyCallable_Check(py_fn)) {
        log(LOG_ERR, "Unable to get %s(): object is not callable",
                name);
        goto on_error;
    }

on_exit:
    return py_fn;

on_error:
    log_python_exception();
    Py_CLEAR(py_fn);
    goto on_exit;
}


static void unload_objects()
{
    const ObjectNames *object = object_names;

    while (object->name) {
        Py_CLEAR(*object->py_ptr);
        ++object;
    }
}


static bool load_objects()
{
    const ObjectNames *object = object_names;

    while (object->name) {
        PyObject *py_parent = NULL;

        if (object->py_parent_ptr) {
            py_parent = *object->py_parent_ptr;
        }
        *object->py_ptr = object->fn(py_parent, object->name);
        if (!*object->py_ptr) {
            return false;
        }
        ++object;
    }

    return true;
}


static PyObject *create_py_long(long val)
{
#if PY_MAJOR_VERSION >= 3
    PyObject *py_long = PyLong_FromLong(val);
#else
    PyObject *py_long = PyInt_FromLong(val);
#endif
    if (!py_long) {
        log(LOG_ERR,
                "Can not create long variable: "
                "PyLong_FromLong()/PyInt_FromLong() failed");
        return NULL;
    }
    return py_long;
}


static bool set_module_constants()
{
    const ModuleConstantNames *module_constant = module_constant_names;

    while (module_constant->name) {
        PyObject *py_long = create_py_long(module_constant->value);
        if (!py_long) {
            log(LOG_ERR, "Can not set constant %s: create_py_long() failed",
                    module_constant->name);
            goto on_error;
        }

        if (PyObject_SetAttrString(
                mod.zabbix, module_constant->name, py_long) == -1) {
            log(LOG_ERR, "Can not set %s: PyObject_SetAttrString() failed",
                    module_constant->name);
            goto on_error;
        }

        ++module_constant;

        Py_DECREF(py_long);
        continue;

    on_error:
        log_python_exception();
        Py_XDECREF(py_long);
        return false;
    }

    return true;
}


static bool get_int_from_py(PyObject *py_long, int *result, bool *has_value)
{
    long value;

    if (py_long == Py_None) {
        if (has_value) {
            *has_value = false;
            return true;
        } else {
            log(LOG_ERR,
                    "Unable to get integer value from python: "
                    "value is None");
            goto on_error;
        }
    }

    if (PyLong_Check(py_long)) {
        value = PyLong_AsLong(py_long);
        if ((value == -1) && PyErr_Occurred()) {
            log(LOG_ERR,
                    "Unable to get integer value from python: "
                    "PyLong_AsLong() failed");
            goto on_error;
        }
#if PY_MAJOR_VERSION == 2
    } else if (PyInt_Check(py_long)) {
        value = PyInt_AsLong(py_long);
        if ((value == -1) && PyErr_Occurred()) {
            log(LOG_ERR,
                    "Unable to get integer value from python: "
                    "PyInt_AsLong() failed");
            goto on_error;
        }
#endif
    } else {
        log(LOG_ERR,
                "Unable to get integer value from python: "
                "value is not an integer");
        goto on_error;
    }

    if ((value < INT_MIN) || (value > INT_MAX)) {
        log(LOG_ERR,
                "Unable to get integer value from python: "
                "value out of bounds of int");
        goto on_error;
    }

    *result = (int) value;
    if (has_value) {
        *has_value = true;
    }
    return true;

on_error:
    log_python_exception();
    return false;
}


static bool get_uint64_from_py(PyObject *py_long, uint64_t *result,
        bool *has_value)
{
    uint64_t value;

    if (py_long == Py_None) {
        if (has_value) {
            *has_value = false;
            return true;
        } else {
            log(LOG_ERR,
                    "Unable to get uint64 value from python: "
                    "value is None");
            goto on_error;
        }
    }

    if (PyLong_Check(py_long)) {
        unsigned long long ull_value = PyLong_AsUnsignedLongLong(py_long);
        if ((ull_value == (unsigned long long) -1) && PyErr_Occurred()) {
            log(LOG_ERR,
                    "Unable to get uint64 value from python: "
                    "PyLong_AsUnsignedLongLong() failed");
            goto on_error;
        }
        value = (uint64_t) ull_value;
#if PY_MAJOR_VERSION == 2
    } else if (PyInt_Check(py_long)) {
        long l_value = PyInt_AsLong(py_long);
        if ((l_value == -1) && PyErr_Occurred()) {
            log(LOG_ERR,
                    "Unable to get uint64 value from python: "
                    "PyInt_AsLong() failed");
            goto on_error;
        }
        if (l_value < 0) {
            log(LOG_ERR,
                    "Unable to get uint64 value from python: "
                    "value out of bounds of uint64_t");
            goto on_error;
        }
        value = (uint64_t) l_value;
#endif
    } else {
        log(LOG_ERR,
                "Unable to get uint64 value from python: "
                "value is not an integer");
        goto on_error;
    }

    *result = (uint64_t) value;
    if (has_value) {
        *has_value = true;
    }
    return true;

on_error:
    log_python_exception();
    return false;
}


static bool get_double_from_py(PyObject *py_float, double *result,
        bool *has_value)
{
    double value;

    if (py_float == Py_None) {
        if (has_value) {
            *has_value = false;
            return true;
        } else {
            log(LOG_ERR,
                    "Unable to get double value from python: "
                    "value is None");
            goto on_error;
        }
    }

    value = PyFloat_AsDouble(py_float);
    if ((value == -1.0) && PyErr_Occurred()) {
        log(LOG_ERR,
                "Unable to get double value from python: "
                "PyFloat_AsDouble() failed");
        goto on_error;
    }

    *result = value;
    if (has_value) {
        *has_value = true;
    }
    return true;

on_error:
    log_python_exception();
    return false;
}


static bool get_string_from_py(PyObject *py_str, char **string, bool optional)
{
    bool no_errors = true;
    PyObject *py_utf8_str = NULL;
    char *result = NULL;

    if (py_str == Py_None) {
        if (optional) {
            goto on_exit;
        } else {
            log(LOG_ERR,
                    "Unable to get string from python: "
                    "value is None");
            goto on_error;
        }
    }

    if (PyUnicode_Check(py_str)) {
        py_utf8_str = PyUnicode_AsUTF8String(py_str);
        if (!py_utf8_str) {
            log(LOG_ERR,
                    "Unable to get string from python: "
                    "PyUnicode_AsUTF8String() failed");
            goto on_error;
        }
    } else {
#if PY_MAJOR_VERSION >= 3
        log(LOG_ERR, "Unable to get string from python: object is not unicode");
        goto on_error;
#else
        /* We assume that on Python 2 object is utf8 string already. */
        py_utf8_str = py_str;
        Py_INCREF(py_utf8_str);
#endif
    }

#if PY_MAJOR_VERSION >= 3
    const char *py_internal_string = PyBytes_AsString(py_utf8_str);
#else
    const char *py_internal_string = PyString_AsString(py_utf8_str);
#endif
    if (!py_internal_string) {
        log(LOG_ERR,
                "Unable to get string from python: "
                "PyBytes_AsString()/PyString_AsString() failed");
        goto on_error;
    }

    result = strdup(py_internal_string);
    if (!result) {
        log(LOG_ERR, "Unable to get string from python: strdup() failed");
        goto on_error;
    }

on_exit:
    Py_XDECREF(py_utf8_str);

    *string = result;
    return no_errors;

on_error:
    log_python_exception();

    free(result);
    result = NULL;

    no_errors = false;

    goto on_exit;
}


static PyObject *call_py_fn(PyObject *py_fn, PyObject *args)
{
    PyObject *py_ret = PyObject_CallObject(py_fn, args);
    if (!py_ret) {
        log(LOG_ERR, "Python function call failed");
        log_python_exception();
        return NULL;
    }
    return py_ret;
}


static bool call_py_fn_with_none_rc(PyObject *py_fn, PyObject *args)
{
    PyObject *py_ret = call_py_fn(py_fn, args);
    if (!py_ret) {
        return false;
    }
    Py_DECREF(py_ret);
    return true;
}


static bool call_py_fn_with_int_rc(PyObject *py_fn, PyObject *args, int *rc)
{
    PyObject *py_ret = call_py_fn(py_fn, args);
    if (!py_ret) {
        return false;
    }
    bool result = get_int_from_py(py_ret, rc, NULL);
    Py_DECREF(py_ret);

    return result;
}


static PyObject *join_py_strings(const char *separator, PyObject *strings_seq)
{
    PyObject *py_separator = PyUnicode_FromString(separator);
    if (!py_separator) {
        log(LOG_ERR,
                "Unable to join python strings: PyUnicode_FromString() failed");
        log_python_exception();
        return NULL;
    }
    PyObject *py_result = PyUnicode_Join(py_separator, strings_seq);
    if (!py_result) {
        log(LOG_ERR,
                "Unable to join python strings: PyUnicode_Join() failed");
        log_python_exception();
        Py_DECREF(py_separator);
        return NULL;
    }
    Py_DECREF(py_separator);
    return py_result;
}


static void log_python_exception()
{
    PyObject *py_exc_type = NULL;
    PyObject *py_exc_value = NULL;
    PyObject *py_exc_traceback = NULL;
    PyObject *py_fmt_args = NULL;
    PyObject *py_fmt_lines = NULL;
    PyObject *py_formatted_exc = NULL;
    char *formatted_exc = NULL;

    PyErr_Fetch(&py_exc_type, &py_exc_value, &py_exc_traceback);
    if (!py_exc_type && !py_exc_value && !py_exc_traceback) {
        return;
    }
    if (on_python_exception) {
        log(LOG_ERR,
                "Unable to format python exception with traceback: "
                "another python exception occured");
        goto on_error;
        return;
    }
    on_python_exception = true;

    if (!py_exc_value) {
        py_exc_value = Py_None;
        Py_INCREF(py_exc_value);
    }
    if (!py_exc_traceback) {
        py_exc_traceback = Py_None;
        Py_INCREF(py_exc_traceback);
    }

    PyErr_NormalizeException(&py_exc_type, &py_exc_value, &py_exc_traceback);

    if (!mod_traceback.format_exception_fn) {
        log(LOG_ERR,
                "Unable to format python exception with traceback: "
                "traceback.format_exception() is not loaded");
        goto on_error;
    }

    py_fmt_args = PyTuple_Pack(3, py_exc_type, py_exc_value, py_exc_traceback);
    if (!py_fmt_args) {
        log(LOG_ERR,
                "Unable to format python exception with traceback: "
                "PyTuple_Pack() failed");
        goto on_error;
    }

    py_fmt_lines = call_py_fn(mod_traceback.format_exception_fn, py_fmt_args);
    if (!py_fmt_lines) {
        log(LOG_ERR, "Unable to format python exception with traceback");
        goto on_error;
    }

    py_formatted_exc = join_py_strings("", py_fmt_lines);
    if (!py_formatted_exc) {
        log(LOG_ERR,
                "Unable to format python exception with traceback: "
                "can not join lines");
        goto on_error;
    }

    if (!get_string_from_py(py_formatted_exc, &formatted_exc, false))
    {
        log(LOG_ERR,
                "Unable to format python exception with traceback: "
                "can not convert to string");
        goto on_error;
    }

    log(LOG_ERR, "Last python exception:\n%s", formatted_exc);

on_exit:
    Py_XDECREF(py_exc_type);
    Py_XDECREF(py_exc_value);
    Py_XDECREF(py_exc_traceback);
    Py_XDECREF(py_fmt_args);
    Py_XDECREF(py_fmt_lines);
    Py_XDECREF(py_formatted_exc);

    free(formatted_exc);
    on_python_exception = false;
    return;

on_error:
    PyErr_Clear();
    goto on_exit;
}


#if defined(PYTHON_LIB_NAME)
static bool load_python_lib()
{
    /*
     * Workaround for errors like
     *   ImportError: /usr/lib64/python2.7/lib-dynload/_collectionsmodule.so: undefined symbol: _Py_ZeroStruct
     *
     * Zabbix loads this module with RTLD_LOCAL, but some of the "native"
     * python modules are not directly linked with libpython*.so. As a result,
     * these python modules can not find expected symbols from libpython*.so.
     */
    python_lib_handle = dlopen(PYTHON_LIB_NAME, RTLD_NOW | RTLD_GLOBAL);
    if (!python_lib_handle) {
        log(LOG_ERR, "Unable to load python lib '%s': dlopen() failed",
                PYTHON_LIB_NAME);
        return false;
    }
    return true;
}


static void unload_python_lib()
{
    if (python_lib_handle) {
        if (dlclose(python_lib_handle)) {
            log(LOG_ERR, "dlclose() failed");
        }
        python_lib_handle = NULL;
    }
}
#else
inline static bool load_python_lib()
{
    return true;
}


inline static void unload_python_lib()
{
}
#endif


static bool call_init_fn(int *ret_code_ptr)
{
    bool no_errors = true;
    PyObject *py_module_type = NULL;
    PyObject *py_args = NULL;

    py_module_type = PyUnicode_FromString(MODULE_TYPE);
    if (!py_module_type) {
        log(LOG_ERR, "Unable to call init(): PyUnicode_FromString() failed");
        goto on_error;
    }

    py_args = PyTuple_Pack(1, py_module_type);
    if (!py_args) {
        log(LOG_ERR, "Unable to call init(): PyTuple_Pack() for call failed");
        goto on_error;
    }

    if (!call_py_fn_with_int_rc(mod_zabbix.init_fn, py_args, ret_code_ptr)) {
        goto on_error;
    }

on_exit:
    Py_XDECREF(py_module_type);
    Py_XDECREF(py_args);

    return no_errors;

on_error:
    log_python_exception();
    no_errors = false;
    goto on_exit;
}


int zbx_module_init()
{
    int ret_code = ZBX_MODULE_OK;

    log(LOG_INFO, "Initializing (zabbix_%s, python %s)...",
            MODULE_TYPE, PY_VERSION);

    if (!set_after_fork_handler()) {
        goto on_error;
    }

    if (!load_python_lib()) {
        goto on_error;
    }

    Py_SetProgramName(program_name);
    Py_Initialize();

    if (!load_objects()) {
        goto on_error;
    }

    if (!set_module_constants()) {
        goto on_error;
    }

    if (!call_init_fn(&ret_code)) {
        goto on_error;
    }

    if (ret_code == ZBX_MODULE_OK) {
        log(LOG_INFO, "Initialization finished successfully");
    } else {
        log(LOG_ERR, "Initialization failed");
    }

on_exit:
    return ret_code;

on_error:
    ret_code = ZBX_MODULE_FAIL;
    unload_objects();
    Py_Finalize();
    unload_python_lib();
    goto on_exit;
}


static bool call_after_fork_fn(bool parent)
{
    PyObject *py_parent = parent? Py_True:Py_False;
    Py_INCREF(py_parent);

    PyObject *py_args = PyTuple_Pack(1, py_parent);
    if (!py_args) {
        log(LOG_ERR,
                "Unable to call after_fork(): PyTuple_Pack() for call failed");
        log_python_exception();
        Py_DECREF(py_parent);
        return false;
    }

    bool ret = call_py_fn_with_none_rc(mod_zabbix.after_fork_fn, py_args);

    Py_DECREF(py_parent);
    Py_DECREF(py_args);
    return ret;
}


static bool check_if_forked()
{
    if (forked_child) {
        forked_child = false;
        log(LOG_INFO, "Fork detected (child %u)", (unsigned) getpid());

        if (Py_IsInitialized()) {
            PyOS_AfterFork();
        }

        if (!call_after_fork_fn(false)) {
            return false;
        }
    }

    if (forked_parent) {
        forked_parent = false;
        /* No logging here, as it could generate a lot of spam in syslog,
         * because zabbix spawns new processes periodically for some metrics. */
        if (!call_after_fork_fn(true)) {
            return false;
        }
    }

    return true;
}


static bool get_string_attr_from_py(PyObject *py_obj, const char *name,
        char **string, bool optional)
{
    PyObject *py_attr = get_py_attr(py_obj, name);
    if (!py_attr) {
        return false;
    }

    bool ret = get_string_from_py(py_attr, string, optional);
    Py_DECREF(py_attr);
    return ret;
}


static bool get_uint64_attr_from_py(PyObject *py_obj, const char *name,
        uint64_t *result, bool *has_value)
{
    PyObject *py_attr = get_py_attr(py_obj, name);
    if (!py_attr) {
        return false;
    }

    bool ret = get_uint64_from_py(py_attr, result, has_value);
    Py_DECREF(py_attr);
    return ret;
}


static bool get_double_attr_from_py(PyObject *py_obj, const char *name,
        double *result, bool *has_value)
{
    PyObject *py_attr = get_py_attr(py_obj, name);
    if (!py_attr) {
        return false;
    }

    bool ret = get_double_from_py(py_attr, result, has_value);
    Py_DECREF(py_attr);
    return ret;
}


static void set_failure_result(AGENT_RESULT *result)
{
    if (result->type & AR_STRING) {
        free(result->str);
        result->str = NULL;
    }
    if (result->type & AR_TEXT) {
        free(result->text);
        result->text = NULL;
    }
    if (result->type & AR_MESSAGE) {
        free(result->msg);
        result->msg = NULL;
    }
    result->type &= ~(AR_UINT64 | AR_DOUBLE | AR_STRING | AR_TEXT | AR_MESSAGE);

    char *message = strdup(PROJECT_NAME " failed to return value: "
            "see syslog for details");
    if (message) {
        SET_MSG_RESULT(result, message);
    } else {
        /* lol */
        log(LOG_ERR, "Unable to allocate memory for error message: "
                "strdup() failed");
    }
}


static PyObject *convert_request_params(const AGENT_REQUEST *request)
{
    PyObject *py_arg_params = PyTuple_New(request->nparam);
    if (!py_arg_params) {
        log(LOG_ERR, "Unable to get value '%s': PyTuple_New() failed",
                request->key);
        return NULL;
    }

    for (int i = 0; i < request->nparam; ++i) {
        PyObject *py_param = PyUnicode_FromString(get_rparam(request, i));
        if (!py_param) {
            log(LOG_ERR,
                    "Unable to get value '%s': "
                    "PyUnicode_FromString() failed for parameter",
                    request->key);
            log_python_exception();
            Py_DECREF(py_arg_params);
            return NULL;
        }

        /* "Steals" py_param reference, no DECREF required on success. */
        int ret = PyTuple_SetItem(py_arg_params, i, py_param);
        if (ret) {
            log(LOG_ERR,
                    "Unable to get value '%s': "
                    "PyTuple_SetItem() failed for parameter",
                    request->key);
            log_python_exception();
            Py_DECREF(py_arg_params);
            Py_DECREF(py_param);
            return NULL;
        }
    }

    return py_arg_params;
}


static PyObject *convert_request(const AGENT_REQUEST *request)
{
    PyObject *py_arg_key = NULL;
    PyObject *py_arg_params = NULL;
    PyObject *py_arg_mtime = NULL;
    PyObject *py_request_args = NULL;
    PyObject *py_request = NULL;

    py_arg_key = PyUnicode_FromString(request->key);
    if (!py_arg_key) {
        log(LOG_ERR,
                "Unable to get value '%s': "
                "PyUnicode_FromString() failed for key",
                request->key);
        goto on_error;
    }

    py_arg_params = convert_request_params(request);

    py_arg_mtime = create_py_long(request->mtime);
    if (!py_arg_mtime) {
        log(LOG_ERR, "Unable to get value '%s': create_py_long() failed",
                request->key);
        goto on_error;
    }

    py_request_args = PyTuple_Pack(3, py_arg_key, py_arg_params, py_arg_mtime);
    if (!py_request_args) {
        log(LOG_ERR,
                "Unable to get value '%s': "
                "PyTuple_Pack() for request failed",
                request->key);
        goto on_error;
    }

    py_request = call_py_fn(mod_zabbix.request_type, py_request_args);
    if (!py_request) {
        log(LOG_ERR, "Unable to get value '%s': can not create request object",
                request->key);
        goto on_error;
    }

on_exit:
    Py_XDECREF(py_request_args);
    Py_XDECREF(py_arg_mtime);
    Py_XDECREF(py_arg_params);
    Py_XDECREF(py_arg_key);
    return py_request;

on_error:
    log_python_exception();
    Py_CLEAR(py_request);
    goto on_exit;
}


static bool call_get_value_fn(PyObject *py_request, PyObject *py_result,
        int *rc, const char *request_key)
{
    PyObject *py_args = PyTuple_Pack(2, py_request, py_result);
    if (!py_args) {
        log(LOG_ERR,
                "Unable to get value '%s': "
                "PyTuple_Pack() for call failed",
                request_key);
        log_python_exception();
        return false;
    }

    bool ret = call_py_fn_with_int_rc(mod_zabbix.get_value_fn, py_args, rc);
    Py_DECREF(py_args);
    if (!ret) {
        log(LOG_ERR, "Unable to get value '%s': call to get_value() failed",
                request_key);
        return false;
    }

    return true;
}


static bool convert_result(PyObject *py_result, AGENT_RESULT *result,
        const char *request_key)
{
    uint64_t ui64;
    bool has_ui64_val;
    if (!get_uint64_attr_from_py(py_result, result_attr_ui64,
            &ui64, &has_ui64_val)) {
        log(LOG_ERR,
                "Unable to get value '%s': "
                "unable to get attribute '%s'",
                request_key, result_attr_ui64);
        return false;
    }
    if (has_ui64_val) {
        SET_UI64_RESULT(result, ui64);
    }

    double dbl;
    bool has_dbl_val;
    if (!get_double_attr_from_py(py_result, result_attr_dbl,
            &dbl, &has_dbl_val)) {
        log(LOG_ERR,
                "Unable to get value '%s': "
                "unable to get attribute '%s'",
                request_key, result_attr_dbl);
        return false;
    }
    if (has_dbl_val) {
        SET_DBL_RESULT(result, dbl);
    }

    char *str = NULL;
    if (!get_string_attr_from_py(py_result, result_attr_str, &str, true)) {
        log(LOG_ERR,
                "Unable to get value '%s': "
                "unable to get attribute '%s'",
                request_key, result_attr_str);
        return false;
    }
    if (str) {
        SET_STR_RESULT(result, str);
    }

    char *text = NULL;
    if (!get_string_attr_from_py(py_result, result_attr_text, &text, true)) {
        log(LOG_ERR,
                "Unable to get value '%s': "
                "unable to get attribute '%s'",
                request_key, result_attr_text);
        return false;
    }
    if (text) {
        SET_TEXT_RESULT(result, text);
    }

    char *msg = NULL;
    if (!get_string_attr_from_py(py_result, result_attr_msg, &msg, true)) {
        log(LOG_ERR,
                "Unable to get value '%s': "
                "unable to get attribute '%s'",
                request_key, result_attr_msg);
        return false;
    }
    if (msg) {
        SET_MSG_RESULT(result, msg);
    }

    return true;
}


static int zbx_module_get_value(AGENT_REQUEST *request, AGENT_RESULT *result)
{
    int ret = SYSINFO_RET_OK;

    PyObject *py_request = NULL;
    PyObject *py_result = NULL;

    if (!check_if_forked()) {
        goto on_error;
    }

    py_request = convert_request(request);
    if (!py_request) {
        goto on_error;
    }

    py_result = call_py_fn(mod_zabbix.result_type, NULL);
    if (!py_request) {
        log(LOG_ERR, "Unable to get value '%s': can not create result object",
                request->key);
        goto on_error;
    }

    if (!call_get_value_fn(py_request, py_result, &ret, request->key)) {
        goto on_error;
    }

    if (!convert_result(py_result, result, request->key)) {
        goto on_error;
    }

on_exit:
    Py_XDECREF(py_result);
    Py_XDECREF(py_request);
    return ret;

on_error:
    set_failure_result(result);
    ret = SYSINFO_RET_FAIL;
    goto on_exit;
}


static void free_item(ZBX_METRIC *item)
{
    free(item->key);
    free(item->test_param);
}


static bool add_item(
        int *n_items_ptr,
        ZBX_METRIC **item_list_ptr,
        PyObject *py_items_iterator)
{
    bool continue_flag = true;

    ZBX_METRIC *new_item_list = NULL;
    PyObject *py_item = NULL;
    ZBX_METRIC item = {0};

    py_item = PyIter_Next(py_items_iterator);
    if (py_item) {
        item.function = zbx_module_get_value;

        if (!get_string_attr_from_py(py_item, item_attr_key,
                &item.key, false)) {
            log(LOG_ERR,
                    "Unable to add new item: "
                    "unable to get attribute '%s'",
                    item_attr_key);
            goto on_error;
        }

        uint64_t flags;
        bool has_flags;
        if (!get_uint64_attr_from_py(py_item, item_attr_flags,
                &flags, &has_flags)) {
            log(LOG_ERR,
                    "Unable to add new item: "
                    "unable to get attribute '%s'",
                    item_attr_flags);
            goto on_error;
        }
        if (has_flags) {
            item.flags = (unsigned int) flags;
        }

        if (!get_string_attr_from_py(py_item, item_attr_test_param,
                &item.test_param, true)) {
            log(LOG_ERR,
                    "Unable to add new item: "
                    "unable to get attribute '%s'",
                    item_attr_test_param);
            goto on_error;
        }
    } else {
        continue_flag = false;
        if (PyErr_Occurred()) {
            log(LOG_ERR,
                    "Unable to add new item: "
                    "python exception occured in PyIter_Next()");
            goto on_error;
        }
    }

append_item:
    /* TODO: Allocate space for multiple items at once. */
    new_item_list = realloc(
            *item_list_ptr,
            (*n_items_ptr + 1) * sizeof(**item_list_ptr));
    if (new_item_list) {
        new_item_list[*n_items_ptr] = item;
        *item_list_ptr = new_item_list;
        if (continue_flag) {
            ++*n_items_ptr;
        }
    } else {
        log(LOG_ERR,
                "Unable to add new item: "
                "realloc() failed");
        continue_flag = false;
        *n_items_ptr = -1;

        free_item(&item);
    }

on_exit:
    Py_XDECREF(py_item);

    return continue_flag;

on_error:
    log_python_exception();

    free_item(&item);

    if (continue_flag) {
        goto on_exit;
    }

    /* Finalize list. */
    memset(&item, 0, sizeof(item));
    goto append_item;
}


static void free_item_list(ZBX_METRIC *list)
{
    if (list) {
        ZBX_METRIC *item = list;

        while (item->key) {
            free_item(item);
            ++item;
        }
        free(list);
    }
}


ZBX_METRIC *zbx_module_item_list()
{
    if (item_list) {
        return item_list;
    }

    ZBX_METRIC *result = NULL;
    static ZBX_METRIC result_on_failure[] = {
        {0},
    };
    int n_items = 0;

    PyObject *py_item_list_fn_ret = NULL;
    PyObject *py_items_iterator = NULL;

    log(LOG_INFO, "Creating list of supported items...");

    if (!check_if_forked()) {
        goto on_error;
    }

    py_item_list_fn_ret = PyObject_CallObject(mod_zabbix.item_list_fn, NULL);
    if (!py_item_list_fn_ret) {
        log(LOG_ERR, "Unable to get item list: call to item_list() failed");
        goto on_error;
    }

    py_items_iterator = PyObject_GetIter(py_item_list_fn_ret);
    if (!py_items_iterator) {
        log(LOG_ERR, "Unable to get item list: PyObject_GetIter() failed");
        goto on_error;
    }

    while (add_item(&n_items, &result, py_items_iterator));
    if (n_items == -1) {
        log(LOG_ERR, "Unable to get item list: fatal error when adding items");
        goto on_error;
    }

    item_list = result;

    log(LOG_INFO, "Found %d supported items", n_items);

on_exit:
    Py_XDECREF(py_items_iterator);
    Py_XDECREF(py_item_list_fn_ret);

    return result;

on_error:
    log_python_exception();

    free_item_list(result);
    result = result_on_failure;

    goto on_exit;
}


int zbx_module_uninit()
{
    int ret_code = ZBX_MODULE_OK;

    log(LOG_INFO, "Uninitializing...");

    if (!check_if_forked()) {
        goto on_error;
    }

    free_item_list(item_list);
    item_list = NULL;

    if (!call_py_fn_with_int_rc(mod_zabbix.uninit_fn, NULL, &ret_code)) {
        goto on_error;
    }

    if (ret_code == ZBX_MODULE_OK) {
        log(LOG_INFO, "Uninitialization finished successfully");
    } else {
        log(LOG_ERR, "Uninitialization failed");
    }

on_exit:
    unload_objects();
    Py_Finalize();
    unload_python_lib();
    return ret_code;

on_error:
    ret_code = ZBX_MODULE_FAIL;
    goto on_exit;
}
