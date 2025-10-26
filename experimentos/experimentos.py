#!/usr/bin/env python3

import math
import statistics
import csv
from pathlib import Path
import matplotlib.pyplot as plt
import paramiko
import threading

# CONFIG GERAL

REPS = 5

N_LIST = [
    1_000,
    10_000,
    100_000,
    1_000_000,
    10_000_000,
    100_000_000,
    1_000_000_000,
    10_000_000_000,
]

THREAD_LIST = [1, 2, 4, 6, 8]

IMPLEMENTATIONS = [
    {
        "name": "seq_prof",
        "src": "seq_prof.c",
        "bin": "./seq_prof_exec",
        "cflags": [
            "gcc-11",
            "seq_prof.c",
            "-fopenmp",
            "-lm",
            "-o",
            "seq_prof_exec",
        ],
        "threads_to_test": [1],
        "baseline_for": [],
        "visible": False,
    },
    {
        "name": "par_prof",
        "src": "par_prof.c",
        "bin": "./par_prof_exec",
        "cflags": [
            "gcc-11",
            "par_prof.c",
            "-fopenmp",
            "-lm",
            "-o",
            "par_prof_exec",
        ],
        "threads_to_test": THREAD_LIST,
        "baseline_for": ["par_prof"],
        "visible": True,
    },
    {
        "name": "codigo",
        "src": "codigo.c",
        "bin": "./codigo",
        "cflags": [
            "gcc-11",
            "codigo.c",
            "-fopenmp",
            "-O3",
            "-march=native",
            "-fno-math-errno",
            "-fno-trapping-math",
            "-ffast-math",
            "-lm",
            "-o",
            "codigo",
        ],
        "threads_to_test": THREAD_LIST,
        "baseline_for": [],
        "visible": True,
    },
    {
        "name": "codigo_novec",
        "src": "codigo_novec.c",
        "bin": "./codigo_novec",
        "cflags": [
            "gcc-11",
            "codigo_novec.c",
            "-fopenmp",
            "-lm",
            "-o",
            "codigo_novec",
        ],
        "threads_to_test": [1],
        "baseline_for": ["codigo"],
        "visible": False,
    },
]

REMOTES = {
    "hal01": 2210,
    "hal02": 2220,
    "hal03": 2230,
    "hal04": 2240,
    "hal05": 2250,
    "hal06": 2260,
    "hal07": 2270,
    "hal08": 2280,
    "hal09": 2290,
    "hal10": 22100,
    "hal13": 22130,
}


# FUNÇÕES AUX


def run_all_remote_experiments(password: str):
    threads: list[threading.Thread] = []
    raw_rows = []
    raw_rows_lock = threading.Lock()

    for remote_name, port in REMOTES.items():
        thread = threading.Thread(
            target=run_remote_experiment,
            args=(remote_name, port, password, raw_rows, raw_rows_lock),
            name="thread_" + remote_name,
        )
        threads.append(thread)
        thread.start()

    for thread in threads:
        thread.join()

    return raw_rows


def run_remote_experiment(
    remote_name: str,
    port: int,
    password: str,
    parent_raw_rows: list[dict],
    raw_rows_lock: threading.Lock,
):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname="andromeda.lasdpc.icmc.usp.br",
        port=port,
        username="ssc903-tb-g05",
        password=password,
    )

    remote_dir = f"/home/ssc903-tb-g05/exp_{remote_name}"
    stdin, stdout, stderr = client.exec_command(f"mkdir -p {remote_dir}")
    if stdout.channel.recv_exit_status() != 0:
        raise RuntimeError(
            f"[{remote_name}] Could not create remote dir {remote_dir}: {stderr.read().decode()}"
        )

    copy_source_files(client, remote_name, remote_dir)

    compile_all(client, remote_name, remote_dir)
    local_raw_runs = collect_all_runs(client, remote_name, remote_dir)
    client.close()

    raw_rows_lock.acquire()
    parent_raw_rows.extend(local_raw_runs)
    raw_rows_lock.release()


def copy_source_files(client: paramiko.SSHClient, remote_name: str, remote_dir: str):
    sftp_client = client.open_sftp()
    for impl in IMPLEMENTATIONS:
        file = impl["src"]
        try:
            sftp_client.put(file, f"{remote_dir}/{file}")
        except Exception:
            print(f"[{remote_name}] Error copying {file} to remote")
            raise
    sftp_client.close()


def compile_all(client: paramiko.SSHClient, remote_name: str, remote_dir: str):
    for impl in IMPLEMENTATIONS:
        print(f"[{remote_name}] Compiling {impl['name']} ...")
        compile_cmd = " ".join(impl["cflags"])
        full_cmd = f"cd {remote_dir} && {compile_cmd}"
        stdin, stdout, stderr = client.exec_command(full_cmd)
        if stdout.channel.recv_exit_status() != 0:
            raise RuntimeError(
                f"[{remote_name}] Compilation failed for {impl['name']} {stderr.read().decode()}"
            )
    print(f"[{remote_name}] Compilation OK for all.")


def run_once(
    client: paramiko.SSHClient,
    bin_path: str,
    N: int,
    T: int,
    remote_name: str,
    remote_dir: str,
):
    """
    Executa ./bin_path N T
    Espera linha:
    impl_name,Npoints,threads,elapsed_s,pi_est,abs_err
    """

    cmd = [str(Path(remote_dir, bin_path)), str(N), str(T)]
    stdin, stdout, stderr = client.exec_command(" ".join(cmd))
    output = stdout.read().decode()
    line = output.strip().split(",")

    if len(line) != 6:
        raise RuntimeError(
            f"[{remote_name}] Unexpected output from {bin_path}: {output}\n\n{stderr.read().decode()}"
        )

    impl_name = line[0]
    Npoints = int(line[1])
    threads = int(line[2])
    elapsed_s = float(line[3])
    pi_est = float(line[4])
    abs_err = float(line[5])

    return {
        "impl": impl_name,
        "remote": remote_name,
        "Npoints": Npoints,
        "threads": threads,
        "time_s": elapsed_s,
        "pi_est": pi_est,
        "err_abs": abs_err,
    }


def collect_all_runs(client: paramiko.SSHClient, remote_name: str, remote_dir: str):
    raw_rows = []
    for impl in IMPLEMENTATIONS:
        impl_name = impl["name"]
        bin_path = impl["bin"]
        for N in N_LIST:
            for T in impl["threads_to_test"]:
                for rep in range(REPS):
                    print(
                        f"[{remote_name}] Running {impl_name} N={N} T={T} rep={rep + 1}/{REPS} ..."
                    )
                    r = run_once(client, bin_path, N, T, remote_name, remote_dir)
                    raw_rows.append(r)
    return raw_rows


def save_csv_raw(raw_rows, path="raw_runs.csv"):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            ["impl", "remote", "Npoints", "threads", "time_s", "pi_est", "err_abs"]
        )
        for r in raw_rows:
            w.writerow(
                [
                    r["impl"],
                    r["remote"],
                    r["Npoints"],
                    r["threads"],
                    r["time_s"],
                    r["pi_est"],
                    r["err_abs"],
                ]
            )
    print(f"Saved raw data -> {path}")


def build_baseline_map():
    """
    Retorna um dict:
        baseline_map[target_impl] = baseline_impl
    Ex:
        par_prof -> par_prof
        par_final -> par_final_novec
    """
    baseline_map = {}

    # cada impl declara em "baseline_for": quem ela serve como baseline
    for impl in IMPLEMENTATIONS:
        base_name = impl["name"]
        for target in impl["baseline_for"]:
            baseline_map[target] = base_name

        if base_name not in baseline_map:
            if 1 in impl["threads_to_test"]:
                baseline_map[base_name] = base_name

    return baseline_map


def summarize(raw_rows):
    # 1. média/ desvio agrupando execuções
    groups = {}
    for row in raw_rows:
        key = (row["impl"], row["Npoints"], row["threads"])
        groups.setdefault(key, []).append(row)

    stats = {}
    for key, rows in groups.items():
        impl, Npoints, threads = key
        times = [r["time_s"] for r in rows]
        pis = [r["pi_est"] for r in rows]
        errs = [r["err_abs"] for r in rows]

        stats[key] = {
            "impl": impl,
            "Npoints": Npoints,
            "threads": threads,
            "time_mean_s": statistics.mean(times),
            "time_std_s": statistics.pstdev(times) if len(times) > 1 else 0.0,
            "pi_mean": statistics.mean(pis),
            "err_abs_mean": statistics.mean(errs),
        }

    baseline_map = build_baseline_map()

    seq_baseline_time = {}
    for key, st in stats.items():
        impl, Npoints, threads = key
        if impl == "seq_prof" and threads == 1:
            seq_baseline_time[Npoints] = st["time_mean_s"]

    summary_rows = []
    for key, st in stats.items():
        impl = st["impl"]
        Npoints = st["Npoints"]
        threads = st["threads"]

        base_impl = baseline_map.get(impl, None)

        speedup_rel = math.nan
        efficiency = math.nan

        if base_impl is not None:
            base_key = (base_impl, Npoints, 1)  # baseline sempre 1 thread
            if base_key in stats:
                baseline_time = stats[base_key]["time_mean_s"]
                speedup_rel = baseline_time / st["time_mean_s"]
                if threads > 0:
                    efficiency = speedup_rel / threads

        speedup_abs = math.nan
        if Npoints in seq_baseline_time:
            seq_t = seq_baseline_time[Npoints]
            # mesmo seq_t pra todo mundo (inclusive seq_prof resultará em ~=1)
            speedup_abs = seq_t / st["time_mean_s"]

        summary_rows.append(
            {
                "impl": impl,
                "Npoints": Npoints,
                "threads": threads,
                "time_mean_s": st["time_mean_s"],
                "time_std_s": st["time_std_s"],
                "pi_mean": st["pi_mean"],
                "err_abs_mean": st["err_abs_mean"],
                "speedup_abs": speedup_abs,
                "speedup_rel": speedup_rel,
                "efficiency": efficiency,
            }
        )

    return summary_rows


def save_csv_summary(summary_rows, path="summary.csv"):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "impl",
                "Npoints",
                "threads",
                "time_mean_s",
                "time_std_s",
                "pi_mean",
                "err_abs_mean",
                "speedup_abs",
                "speedup_rel",
                "efficiency",
            ]
        )
        for r in summary_rows:
            w.writerow(
                [
                    r["impl"],
                    r["Npoints"],
                    r["threads"],
                    r["time_mean_s"],
                    r["time_std_s"],
                    r["pi_mean"],
                    r["err_abs_mean"],
                    r["speedup_abs"],
                    r["speedup_rel"],
                    r["efficiency"],
                ]
            )
    print(f"Saved summary -> {path}")


def is_visible_impl(name):
    for impl in IMPLEMENTATIONS:
        if impl["name"] == name:
            return impl["visible"]
    return False


def plot_time(summary_rows, outdir):
    # Tempo vs Threads, separado por implementação, e segmentado por Npoints
    # vamos fazer um gráfico por Npoints, cada curva = impl
    Path(outdir).mkdir(exist_ok=True)

    per_N = {}
    for r in summary_rows:
        per_N.setdefault(r["Npoints"], {}).setdefault(r["impl"], []).append(r)

    for Npoints, impl_map in per_N.items():
        plt.figure()
        for impl, rows in impl_map.items():
            rows_sorted = sorted(rows, key=lambda x: x["threads"])
            x = [rr["threads"] for rr in rows_sorted]
            y = [rr["time_mean_s"] for rr in rows_sorted]
            yerr = [rr["time_std_s"] for rr in rows_sorted]
            plt.errorbar(x, y, yerr=yerr, marker="o", capsize=4, label=impl)
        plt.xlabel("Threads")
        plt.ylabel("Tempo médio (s)")
        plt.title(f"Tempo de Resposta vs. Número de Threads (N={Npoints})")
        plt.legend()
        outfile = Path(outdir) / f"time_vs_threads_N{Npoints}.png"
        plt.savefig(outfile, dpi=200, bbox_inches="tight")
        print(f"Saved {outfile}")


def plot_speedup_abs(summary_rows, outdir):
    # Speedup absoluto vs Threads (baseline = seq_prof 1 thread)
    per_N = {}
    for r in summary_rows:
        if not is_visible_impl(r["impl"]):
            continue
        per_N.setdefault(r["Npoints"], {}).setdefault(r["impl"], []).append(r)

    for Npoints, impl_map in per_N.items():
        plt.figure()
        for impl, rows in impl_map.items():
            rows_sorted = sorted(rows, key=lambda x: x["threads"])
            x = [rr["threads"] for rr in rows_sorted]
            y = [rr["speedup_abs"] for rr in rows_sorted]
            plt.plot(x, y, marker="o", label=impl)
        plt.xlabel("Threads")
        plt.ylabel("Speedup (T_{seq}/T_p}")
        plt.title(f"Speedup em relação ao código sequencial original (N={Npoints})")
        plt.legend()
        outfile = Path(outdir) / f"speedup_abs_vs_threads_N{Npoints}.png"
        plt.savefig(outfile, dpi=200, bbox_inches="tight")
        print(f"Saved {outfile}")


def plot_speedup_rel(summary_rows, outdir):
    # Speedup relativo vs Threads
    per_N = {}
    for r in summary_rows:
        if not is_visible_impl(r["impl"]):
            continue
        per_N.setdefault(r["Npoints"], {}).setdefault(r["impl"], []).append(r)

    for Npoints, impl_map in per_N.items():
        plt.figure()
        for impl, rows in impl_map.items():
            rows_sorted = sorted(rows, key=lambda x: x["threads"])
            x = [rr["threads"] for rr in rows_sorted]
            y = [rr["speedup_rel"] for rr in rows_sorted]
            plt.plot(x, y, marker="o", label=impl)
        plt.xlabel("Threads")
        plt.ylabel("Speedup relativo (T_1/T_p)")
        plt.title(f"Speedup relativo (N={Npoints})")
        plt.legend()
        outfile = Path(outdir) / f"speedup_rel_vs_threads_N{Npoints}.png"
        plt.savefig(outfile, dpi=200, bbox_inches="tight")
        print(f"Saved {outfile}")


def plot_efficiency(summary_rows, outdir):
    # Eficiência paralela interna vs Threads para cada implementação paralela
    per_N = {}
    for r in summary_rows:
        if not is_visible_impl(r["impl"]):
            continue
        per_N.setdefault(r["Npoints"], {}).setdefault(r["impl"], []).append(r)

    for Npoints, impl_map in per_N.items():
        plt.figure()
        for impl, rows in impl_map.items():
            rows_sorted = sorted(rows, key=lambda x: x["threads"])
            x = [rr["threads"] for rr in rows_sorted]
            y = [rr["efficiency"] for rr in rows_sorted]
            plt.plot(x, y, marker="o", label=impl)
        plt.xlabel("Threads")
        plt.ylabel("Eficiência")
        plt.title(f"Eficiência em relação número de threads (N={Npoints})")
        plt.legend()
        outfile = Path(outdir) / f"efficiency_vs_threads_N{Npoints}.png"
        plt.savefig(outfile, dpi=200, bbox_inches="tight")
        print(f"Saved {outfile}")


def plot_error_vs_N(summary_rows, outdir, target_threads_list=THREAD_LIST):
    """
    Para cada T em target_threads_list:
      - eixo X = Npoints
      - eixo Y = err_abs_mean (erro médio |pi - pi_est|)
      - uma curva por implementação paralela ("par_prof", "par_final")

    Ignora "seq_prof".
    """
    Path(outdir).mkdir(exist_ok=True)

    # vamos organizar por threads depois por impl
    for Tsel in target_threads_list:
        # coleta pontos desse T
        per_impl = {}
        for r in summary_rows:
            if not is_visible_impl(r["impl"]):
                continue
            if r["threads"] != Tsel:
                continue  # só o T atual

            per_impl.setdefault(r["impl"], []).append(r)

        # se não tem dados pra esse T, pula
        if not per_impl:
            continue

        # plot
        plt.figure()

        for impl, rows in per_impl.items():
            # ordenar por Npoints crescente pra a linha ficar certinha
            rows_sorted = sorted(rows, key=lambda x: x["Npoints"])
            x = [rr["Npoints"] for rr in rows_sorted]
            y = [rr["err_abs_mean"] for rr in rows_sorted]

            plt.plot(x, y, marker="o", label=impl)

        plt.xlabel("N (número total de pontos simulados)")
        plt.ylabel("Erro médio |π̂ − π|")
        plt.title(f"Erro de π em relação a N (threads = {Tsel})")
        plt.legend()
        plt.xscale("log")  # escala log em N ajuda muito a visualizar
        plt.yscale("log")  # erro costuma cair ~1/sqrt(N), log-log fica quase linha reta

        outfile = Path(outdir) / f"error_vs_N_T{Tsel}.png"
        plt.savefig(outfile, dpi=200, bbox_inches="tight")
        print(f"Saved {outfile}")


def main():
    password = input("Enter SSH password for ssc903-tb-g05: ").strip()

    raw_rows = run_all_remote_experiments(password)
    save_csv_raw(raw_rows, "raw_runs.csv")

    summary_rows = summarize(raw_rows)
    save_csv_summary(summary_rows, "summary.csv")

    outdir = "figs"
    Path(outdir).mkdir(exist_ok=True)

    plot_time(summary_rows, outdir)
    plot_speedup_abs(summary_rows, outdir)
    plot_speedup_rel(summary_rows, outdir)
    plot_efficiency(summary_rows, outdir)
    plot_error_vs_N(summary_rows, outdir)

    print("Done.")


if __name__ == "__main__":
    main()
