import logging

from openinference.instrumentation.langchain import LangChainInstrumentor
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from app.config.config import Settings

logger = logging.getLogger(__name__)


def configure_telemetry(settings: Settings) -> None:
    """Configure OTLP trace and metric export for this process.

    Also instruments LangChain, which is what makes prompts, model names and
    token counts appear inside the request span instead of only the HTTP call.
    """
    if not settings.otel_enabled:
        logger.info("Telemetry disabled")
        return

    endpoint = settings.otel_exporter_otlp_endpoint.rstrip("/")
    resource = Resource.create(
        attributes={
            SERVICE_NAME: settings.otel_service_name,
            SERVICE_VERSION: settings.api_version,
        }
    )

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces"))
    )
    trace.set_tracer_provider(tracer_provider)

    metric_reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=f"{endpoint}/v1/metrics")
    )
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(meter_provider)

    LangChainInstrumentor().instrument(tracer_provider=tracer_provider)
    logger.info("Telemetry configured endpoint=%s", endpoint)
