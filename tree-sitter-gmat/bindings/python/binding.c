// Python binding for the tree-sitter-gmat grammar.
//
// Compiled against the CPython stable ABI (Py_LIMITED_API, floor 3.10) together with the
// generated src/parser.c into a single extension module. It exposes one function, language(),
// returning a PyCapsule around the grammar's TSLanguage pointer; the `tree-sitter` runtime
// consumes that capsule via tree_sitter.Language(...). No tree-sitter runtime headers are needed
// to build this — only Python's, plus the self-contained generated parser.

#include <Python.h>

typedef struct TSLanguage TSLanguage;

TSLanguage *tree_sitter_gmat(void);

static PyObject *_binding_language(PyObject *Py_UNUSED(self), PyObject *Py_UNUSED(args)) {
  return PyCapsule_New(tree_sitter_gmat(), "tree_sitter.Language", NULL);
}

static PyMethodDef methods[] = {
    {"language", _binding_language, METH_NOARGS,
     "Get the tree-sitter language capsule for the GMAT grammar."},
    {NULL, NULL, 0, NULL},
};

static struct PyModuleDef module = {
    .m_base = PyModuleDef_HEAD_INIT,
    .m_name = "_binding",
    .m_doc = NULL,
    .m_size = -1,
    .m_methods = methods,
};

PyMODINIT_FUNC PyInit__binding(void) {
  return PyModule_Create(&module);
}
