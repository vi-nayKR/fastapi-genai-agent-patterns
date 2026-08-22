"""OpenTelemetry provider construction and FastAPI instrumentation."""

from fastapi import FastAPI
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter

from agent_patterns import __version__
from agent_patterns.config import Settings


def create_tracer_provider(
    settings: Settings,
    exporter: SpanExporter | None = None,
) -> TracerProvider:
    """Create one service-scoped provider with optional OTLP export."""

    resource = Resource.create(
        {
            "service.name": settings.service_name,
            "service.version": __version__,
            "deployment.environment.name": settings.environment,
        }
    )
    provider = TracerProvider(resource=resource)
    if exporter is not None:
        provider.add_span_processor(SimpleSpanProcessor(exporter))
    elif settings.otlp_endpoint:
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otlp_endpoint))
        )
    return provider


def instrument_fastapi(app: FastAPI, provider: TracerProvider) -> None:
    """Capture inbound HTTP spans with W3C context propagation."""

    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
