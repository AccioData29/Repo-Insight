"""Repositorio sintético: sistema de facturación .NET con problemas sembrados a propósito."""
from __future__ import annotations

from pathlib import Path

import pytest

FILES: dict[str, str] = {
    "README.md": "# Facturación\n\nSistema que recibe facturas escaneadas, extrae sus datos con OCR y las envía a la autoridad tributaria.\n",
    "src/Billing.Api/Billing.Api.csproj": '<Project Sdk="Microsoft.NET.Sdk.Web">\n<PropertyGroup><TargetFramework>net6.0</TargetFramework></PropertyGroup>\n'
        '<ItemGroup><PackageReference Include="Microsoft.EntityFrameworkCore" Version="6.0.0" /><PackageReference Include="Hangfire" Version="1.8.0" />'
        '<PackageReference Include="Tesseract" Version="5.2.0" /><PackageReference Include="Npgsql" Version="7.0.0" /></ItemGroup></Project>\n',
    "src/Billing.Api/appsettings.json": '{\n  "ConnectionStrings": {\n    "Default": "Host=db.prod.internal;Database=billing;Username=app;Password=Sup3rS3cret!"\n  },\n'
        '  "Billing": {\n    "MaxInvoiceAmount": 50000000,\n    "DueDays": 30,\n    "VatPercent": 19\n  },\n  "Logging": {"LogLevel": {"Default": "Information"}}\n}\n',
    "src/Billing.Api/appsettings.Development.json": '{\n  "ConnectionStrings": {"Default": "Host=localhost;Database=billing;Username=dev;Password=devpass123"}\n}\n',
    "src/Billing.Api/Controllers/InvoicesController.cs": '''using Microsoft.AspNetCore.Mvc;

namespace Billing.Api.Controllers
{
    [ApiController]
    [Route("api/[controller]")]
    public class InvoicesController : ControllerBase
    {
        private readonly IInvoiceService _service;
        private readonly OcrService _ocr;
        public InvoicesController(IInvoiceService service, OcrService ocr) { _service = service; _ocr = ocr; }

        [HttpPost("scan")]
        [Authorize(Roles = "Contador,Administrador")]
        public async Task<IActionResult> Scan(IFormFile file)
        {
            var text = _ocr.Read(file.OpenReadStream());
            var m = System.Text.RegularExpressions.Regex.Match(text, @"Total:\\s*(\\d+)");
            return Ok(m.Value);
        }

        [HttpGet("{id}")]
        [AllowAnonymous]
        public IActionResult Get(int id) => Ok(_service.Find(id));

        [HttpPost]
        public IActionResult Create(CreateInvoiceRequest req)
        {
            if (req.Total > 50000000)
                return BadRequest("El monto de la factura supera el máximo permitido por operación");
            var result = _service.Create(req).Result;
            return Ok(result);
        }
    }
}
''',
    "src/Billing.Api/Services/InvoiceService.cs": '''namespace Billing.Api.Services
{
    public interface IInvoiceService { object Find(int id); Task<object> Create(CreateInvoiceRequest r); }

    public class InvoiceService : IInvoiceService
    {
        private readonly InvoiceRepository _repo;
        private readonly TaxAuthorityClient _tax;
        public InvoiceService(InvoiceRepository repo, TaxAuthorityClient tax) { _repo = repo; _tax = tax; }

        public object Find(int id) => _repo.GetById(id);

        public async Task<object> Create(CreateInvoiceRequest r)
        {
            if (r.Customer.Status == CustomerStatus.Blocked)
                throw new BusinessException("No se puede facturar a un cliente bloqueado por cartera");
            if (r.Total > 1000000 && r.Items.Count > 10)
            {
                r.RequiresApproval = true;
            }
            var inv = new Invoice { Status = InvoiceStatus.Draft, Total = r.Total };
            inv.Status = InvoiceStatus.Issued;
            _repo.Save(inv);
            try { await _tax.Send(inv); } catch (Exception) { }
            Task.Run(() => Console.WriteLine("enviado"));
            return inv;
        }
    }
}
''',
    "src/Billing.Api/Services/OcrService.cs": '''using Tesseract;
namespace Billing.Api.Services
{
    public class OcrService
    {
        public string Read(Stream image)
        {
            using var engine = new TesseractEngine("./tessdata", "spa", EngineMode.Default);
            using var pix = Pix.LoadFromMemory(ToBytes(image));
            using var page = engine.Process(pix);
            return page.GetText();
        }
        private byte[] ToBytes(Stream s) { var ms = new MemoryStream(); s.CopyTo(ms); return ms.ToArray(); }
    }
}
''',
    "src/Billing.Api/Data/InvoiceRepository.cs": '''using Npgsql;
namespace Billing.Api.Data
{
    public class InvoiceRepository
    {
        private readonly BillingDbContext _db;
        public InvoiceRepository(BillingDbContext db) { _db = db; }
        public object GetById(int id)
        {
            var sql = "SELECT * FROM invoices WHERE id = " + id;
            return new NpgsqlCommand(sql);
        }
        public void Save(Invoice inv) { _db.Add(inv); _db.SaveChanges(); }
    }
}
''',
    "src/Billing.Api/Clients/TaxAuthorityClient.cs": '''using System.Net.Http;
namespace Billing.Api.Clients
{
    public class TaxAuthorityClient
    {
        private readonly HttpClient _http;
        public TaxAuthorityClient(HttpClient http) { _http = http; }
        public async Task Send(Invoice inv)
        {
            System.Net.ServicePointManager.ServerCertificateValidationCallback += (s, c, ch, e) => true;
            await _http.PostAsync("http://10.20.30.40/api/invoices", null);
            await _http.GetAsync("https://api.dian.example.gov.co/status");
        }
    }
}
''',
    "src/Billing.Api/Models/Invoice.cs": '''using System.ComponentModel.DataAnnotations;
namespace Billing.Api.Models
{
    public enum InvoiceStatus { Draft, Issued, Annulled, Paid }
    public enum CustomerStatus { Active, Blocked }
    public class Invoice
    {
        [Required(ErrorMessage = "El número de factura es obligatorio")]
        [StringLength(20)]
        public string Number { get; set; }

        [Range(1, 50000000)]
        public decimal Total { get; set; }

        public InvoiceStatus Status { get; set; }
    }
    public class CreateInvoiceRequest { public decimal Total { get; set; } public bool RequiresApproval { get; set; } public Customer Customer { get; set; } public List<object> Items { get; set; } }
    public class Customer { public CustomerStatus Status { get; set; } }
}
''',
    "src/Billing.Api/Jobs/ReminderJob.cs": '''using Hangfire;
namespace Billing.Api.Jobs
{
    public class ReminderJob : BackgroundService
    {
        protected override async Task ExecuteAsync(CancellationToken ct)
        {
            RecurringJob.AddOrUpdate("reminders", () => Console.WriteLine("x"), Cron.Daily);
            while (true) { await Task.Delay(TimeSpan.FromMinutes(5)); }
        }
    }
}
''',
    "src/Billing.Api/Workers/MemQueue.cs": "using System.Collections.Concurrent;\npublic class MemQueue { private ConcurrentQueue<int> _q = new(); }\n",
    "src/Billing.Api/Dockerfile": "FROM mcr.microsoft.com/dotnet/aspnet:6.0\n",
    "src/Billing.Api/web.config": '<configuration><connectionStrings><add name="Legacy" connectionString="Server=10.1.2.3;Database=old;User Id=sa;Password=Sa123456;" /></connectionStrings></configuration>\n',
    "db/schema.sql": "CREATE TABLE invoices (id int primary key, total numeric CHECK (total > 0), number varchar(20) UNIQUE);\n",
    "client/package.json": '{"name":"client","scripts":{"start":"ng serve"},"dependencies":{"@angular/core":"^12.0.0"}}\n',
    ".env": "API_KEY=abc123def456ghi789\n",
}


@pytest.fixture(scope="session")
def sample_repo(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("sample")
    for rel, content in FILES.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    # relleno para superar los umbrales de "repo grande" (pruebas / CI / logging)
    for i in range(30):
        (root / f"src/Billing.Api/Utils/Util{i}.cs").parent.mkdir(parents=True, exist_ok=True)
        (root / f"src/Billing.Api/Utils/Util{i}.cs").write_text(f"public static class Util{i} {{ public static int F() => {i}; }}\n")
    return root
