# Airflow + Ray Demo

## 🧪 Experimental Version

This provider is an experimental alpha containing necessary components to orchestrate and schedule Ray tasks using Airflow. It is actively maintained and being developed to bring production-ready workflows to Ray using Airflow. This release contains everything needed to begin building these workflows using the Airflow Taskflow API.

```yaml
Current Release: 0.2.1
```

## Requirements

Visit the [Ray Project page](https://Ray.io/)
for more info on Ray.

> ⚠️ The server version and client version (build) of Ray MUST be the same.

```yaml
- Python Version >= 3.7
- Airflow Version >= 2.0.0
- Ray Version == 1.3.0
- Filelock >= 3.0.0
```

## Modules

- [Ray XCom Backend](./ray_provider/xcom/ray_backend.py): Custom XCom backend to assist operators in moving data between tasks using the Ray API with its internal Plasma store, thereby allowing for in-memory distributed processing and handling of large data objects.
- [Ray Hook](./ray_provider/hooks/ray_client.py): Extension of `Http` hook that uses the Ray client to provide connections to the Ray Server.
- [Ray Decorator](./ray_provider/decorators/ray_decorators.py): Task decorator to be used with the task flow API, combining wrapping the existing airflow `@task` decorate with `Ray.remote` functionality, thereby executing each task on the Ray cluster.

## Configuration and Usage

1. Install the [astro-cli](https://www.astronomer.io/docs/cloud/stable/develop/cli-quickstart). This project was made using the `astro dev init` command, but that has already been done for you.

2. In your Airflow `Dockerfile`, your docker file should look something like this:

    ```Dockerfile
    FROM quay.io/astronomer/ap-airflow:2.0.2-1-buster-onbuild
    USER root
    RUN pip uninstall astronomer-airflow-version-check -y
    USER astro
    ENV AIRFLOW__CORE__XCOM_BACKEND=ray_provider.xcom.ray_backend.RayBackend
    ```

    Check ap-airflow version, if unsure, change to `ap-airflow:latest-onbuild`. Please also feel free to add any pip packages to the `requirements.txt` but note that these packages will only exist in airflow, and will need to be installed on Ray separately.

3. Configure Ray Locally. To run Ray locally, you'll need a minimum 6GB of free memory. To start, in your environment with Ray installed, run:

    ```bash
    (venv)$ Ray start --num-cpus=8 --object-store-memory=7000000000 --head
    ```

    If you have extra resources, you can bump the memory up.

    You should now be able to open the Ray dashboard at [http://127.0.0.1:8265/](http://127.0.0.1:8265/).

4. Start your Airflow environment and open the UI. If you have installed the astro CLI, you can do this
by running `astro dev start`.

5. In the Airflow UI, add an `Airflow Pool` with the following:

    ```bash
    Pool (name): ray_worker_pool
    Slots: 25
    ```

6. If you are running Ray locally, get your IP address by visiting `ipv4.icanhazip.com`

7. In the Airflow UI, add an `Airflow Connection` with the following:

    ```bash
    Conn Id: ray_cluster_connection
    Conn Type: HTTP
    Host: Cluster IP Address, with basic Auth params if needed
    Port: 10001
    ```

8. In your Airflow DAG Python file, you must include the following in your `default_args` dictionary:

    ```python
    from ray_provider.xcom.ray_backend import RayBackend
    .
    .
    .
    default_args = {
        'on_success_callback': RayBackend.on_success_callback,
        'on_failure_callback': RayBackend.on_failure_callback,
        .
        .
        .
    }
    @dag(
        default_args=default_args,
        .
        .
    )
    def ray_example_dag():
        # do stuff
    ```

9. Using the taskflow API, your airflow task should now use the `@ray_task` decorator for any Ray task and add the `ray_conn_id`, parameter as `task_args`, like:

    ```python
    from ray_provider.decorators import ray_task

    default_args = {
        'on_success_callback': RayBackend.on_success_callback,
        'on_failure_callback': RayBackend.on_failure_callback,
        .
        .
        .
    }
    task_args = {"ray_conn_id": "ray_cluster_connection"}
    .
    .
    .
    @dag(
        default_args=default_args,
        .
        .
    )
    def ray_example_dag():

        @ray_task(**task_args)
        def sum_cols(df: pd.DataFrame) -> pd.DataFrame:
            return pd.DataFrame(df.sum()).T
    ```

## Project Contributors and Maintainers

This project is built in collaboration between [Astronomer](https://www.astronomer.io/) and [Anyscale](https://www.anyscale.com/), with active contributions from:

- [Pete DeJoy](https://github.com/petedejoy)
- [Daniel Imberman](https://github.com/dimberman)
- [Rob Deeb](https://github.com/mrrobby)
- [Richard Liaw](https://github.com/richardliaw)
- [Charles Greer](https://github.com/grechaw)
- [Will Drevo](https://github.com/worldveil)
