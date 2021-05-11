FROM quay.io/astronomer/ap-airflow:2.0.2-1-buster-onbuild
USER root
RUN pip uninstall astronomer-airflow-version-check -y
USER astro
ENV AIRFLOW__CORE__XCOM_BACKEND=ray_provider.xcom.ray_backend.RayBackend
