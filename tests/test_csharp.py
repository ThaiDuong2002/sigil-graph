import pytest
from sigil_core.indexer import extract_symbols_csharp, extract_symbols_razor

_CS_SOURCE = """\
using System;
using System.Threading.Tasks;

namespace MyApp.Controllers
{
    [ApiController]
    [Route("api/users")]
    public class UserController : ControllerBase
    {
        private readonly IUserService _svc;

        public UserController(IUserService svc)
        {
            _svc = svc;
        }

        [HttpGet("{id}")]
        public async Task<IActionResult> GetUser(int id)
        {
            var user = await _svc.GetByIdAsync(id);
            return Ok(user);
        }

        public string Name { get; set; }
    }

    public interface IUserService
    {
        Task<User> GetByIdAsync(int id);
    }

    public enum UserStatus
    {
        Active,
        Inactive,
    }
}
"""


def test_extracts_class():
    syms = extract_symbols_csharp(_CS_SOURCE, "src/Controllers/UserController.cs", False)
    names = [s.name for s in syms]
    assert "UserController" in names


def test_extracts_interface():
    syms = extract_symbols_csharp(_CS_SOURCE, "src/Controllers/UserController.cs", False)
    names = [s.name for s in syms]
    assert "IUserService" in names


def test_extracts_enum():
    syms = extract_symbols_csharp(_CS_SOURCE, "src/Controllers/UserController.cs", False)
    names = [s.name for s in syms]
    assert "UserStatus" in names


def test_extracts_method():
    syms = extract_symbols_csharp(_CS_SOURCE, "src/Controllers/UserController.cs", False)
    names = [s.name for s in syms]
    assert "UserController.GetUser" in names


def test_extracts_constructor():
    syms = extract_symbols_csharp(_CS_SOURCE, "src/Controllers/UserController.cs", False)
    names = [s.name for s in syms]
    assert "UserController.UserController" in names


def test_extracts_property():
    syms = extract_symbols_csharp(_CS_SOURCE, "src/Controllers/UserController.cs", False)
    names = [s.name for s in syms]
    assert "UserController.Name" in names


def test_method_kind():
    syms = extract_symbols_csharp(_CS_SOURCE, "src/Controllers/UserController.cs", False)
    get_user = next(s for s in syms if s.name == "UserController.GetUser")
    assert get_user.kind == "method"


def test_class_kind():
    syms = extract_symbols_csharp(_CS_SOURCE, "src/Controllers/UserController.cs", False)
    ctrl = next(s for s in syms if s.name == "UserController")
    assert ctrl.kind == "class"


def test_line_numbers():
    syms = extract_symbols_csharp(_CS_SOURCE, "src/Controllers/UserController.cs", False)
    ctrl = next(s for s in syms if s.name == "UserController")
    # class starts somewhere after line 1
    assert ctrl.start_line > 1
    assert ctrl.end_line > ctrl.start_line


def test_signature_strips_attribute_lines():
    syms = extract_symbols_csharp(_CS_SOURCE, "src/Controllers/UserController.cs", False)
    get_user = next(s for s in syms if s.name == "UserController.GetUser")
    # Signature must NOT contain the [HttpGet("{id}")] attribute
    assert "[HttpGet" not in get_user.signature_text
    assert "GetUser" in get_user.signature_text


def test_source_text_contains_body():
    syms = extract_symbols_csharp(_CS_SOURCE, "src/Controllers/UserController.cs", False)
    get_user = next(s for s in syms if s.name == "UserController.GetUser")
    assert "_svc.GetByIdAsync" in get_user.source_text


def test_is_test_flag():
    syms = extract_symbols_csharp(_CS_SOURCE, "Tests/UserTests.cs", True)
    assert all(s.is_test for s in syms)


# ── Razor (.cshtml) ──────────────────────────────────────────────────────────

_CSHTML_SOURCE = """\
@model MyApp.Models.UserViewModel

<h1>@Model.Name</h1>

@functions {
    private string FormatName(string first, string last)
    {
        return $"{first} {last}";
    }

    private bool IsAdmin()
    {
        return Model.Role == "Admin";
    }
}
"""


def test_razor_extracts_function():
    syms = extract_symbols_razor(_CSHTML_SOURCE, "Views/User/Index.cshtml", False)
    names = [s.name for s in syms]
    assert "FormatName" in names


def test_razor_extracts_multiple_functions():
    syms = extract_symbols_razor(_CSHTML_SOURCE, "Views/User/Index.cshtml", False)
    names = [s.name for s in syms]
    assert "FormatName" in names
    assert "IsAdmin" in names


def test_razor_line_numbers_are_adjusted():
    syms = extract_symbols_razor(_CSHTML_SOURCE, "Views/User/Index.cshtml", False)
    format_name = next(s for s in syms if s.name == "FormatName")
    # @functions block starts at line 5; FormatName should be after line 5
    assert format_name.start_line > 5


def test_razor_no_symbols_without_functions_block():
    source = "@model MyApp.Models.Foo\n<h1>Hello</h1>\n"
    syms = extract_symbols_razor(source, "Views/Foo.cshtml", False)
    assert syms == []
