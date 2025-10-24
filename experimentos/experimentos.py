#!/usr/bin/env python3

import subprocess
import math
import statistics
import csv
from pathlib import Path
import matplotlib.pyplot as plt

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
        "name": "Sequencial",
        "src": "seq_prof.c",
        "bin": "./seq_prof_exec",
        "cflags": [
            "gcc",
            "seq_prof.c",
            "-fopenmp",
            "-lm",
            "-o",
            "seq_prof_exec",
        ],
    },
    {
        "name": "Paralelo Original",
        "src": "par_prof.c",
        "bin": "./par_prof_exec",
        "cflags": [
            "gcc",
            "par_prof.c",
            "-fopenmp",
            "-lm",
            "-o",
            "par_prof_exec",
        ],
    },
    {
        "name": "Paralelo Desenvolvido",
        "src": "codigo.c",
        "bin": "./codigo",
        "cflags": [
            "gcc",
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
    },
]

# FUNÇÕES AUX

def compile_all():
    for impl in IMPLEMENTATIONS:
        print(f"Compiling {impl['name']} ...")
        subprocess.run(impl["cflags"], check=True)
    print("Compilation OK for all.")


def run_once(bin_path, N, T):
    """
    Executa ./bin_path N T
    Espera linha:
    impl_name,Npoints,threads,elapsed_s,pi_est,abs_err
    """
    cmd = [bin_path, str(N), str(T)]
    completed = subprocess.run(cmd, check=True, capture_output=True, text=True)
    line = completed.stdout.strip().split(",")
    if len(line) != 6:
        raise RuntimeError(f"Unexpected output from {bin_path}: {completed.stdout}")

    impl_name = line[0]
    Npoints = int(line[1])
    threads = int(line[2])
    elapsed_s = float(line[3])
    pi_est = float(line[4])
    abs_err = float(line[5])

    return {
        "impl": impl_name,
        "Npoints": Npoints,
        "threads": threads,
        "time_s": elapsed_s,
        "pi_est": pi_est,
        "err_abs": abs_err,
    }


def collect_all_runs():
    raw_rows = []
    for impl in IMPLEMENTATIONS:
        impl_name = impl["name"]

        # só 1 thread para o sequencial
        if impl_name == "seq_prof":
            thread_values = [1]
        else:
            thread_values = THREAD_LIST

        for N in N_LIST:
            for T in thread_values:
                for rep in range(REPS):
                    print(f"Running {impl_name} N={N} T={T} rep={rep+1}/{REPS} ...")
                    r = run_once(impl["bin"], N, T)
                    raw_rows.append(r)

    return raw_rows


def save_csv_raw(raw_rows, path="raw_runs.csv"):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["impl", "Npoints", "threads", "time_s", "pi_est", "err_abs"])
        for r in raw_rows:
            w.writerow(
                [
                    r["impl"],
                    r["Npoints"],
                    r["threads"],
                    r["time_s"],
                    r["pi_est"],
                    r["err_abs"],
                ]
            )
    print(f"Saved raw data -> {path}")


def summarize(raw_rows):
    """
    1) agrupar por (impl, Npoints, threads)
       -> média e desvio de tempo, média de pi e erro
    2) speedup absoluto vs seq_prof(threads=1)
    3) eficiência paralela interna
    """

    groups = {}
    for row in raw_rows:
        key = (row["impl"], row["Npoints"], row["threads"])
        groups.setdefault(key, []).append(row)

    base_stats = {}  # (impl,Npoints,threads)->stats
    for key, rows in groups.items():
        impl, Npoints, threads = key
        times = [r["time_s"] for r in rows]
        pis = [r["pi_est"] for r in rows]
        errs = [r["err_abs"] for r in rows]

        mean_t = statistics.mean(times)
        std_t = statistics.pstdev(times) if len(times) > 1 else 0.0
        mean_pi = statistics.mean(pis)
        mean_err = statistics.mean(errs)

        base_stats[key] = {
            "impl": impl,
            "Npoints": Npoints,
            "threads": threads,
            "time_mean_s": mean_t,
            "time_std_s": std_t,
            "pi_mean": mean_pi,
            "err_abs_mean": mean_err,
        }

    # passo 2: pegar baseline seq_prof com threads=1 pra cada Npoints
    # isso serve p/ speedup absoluto.
    seq_baseline = {}
    for key, st in base_stats.items():
        impl, Npoints, threads = key
        if impl == "seq_prof" and threads == 1:
            seq_baseline[Npoints] = st["time_mean_s"]

    # passo 3: montar lista final calculando métricas
    summary_rows = []
    for key, st in base_stats.items():
        impl, Npoints, threads = key

        # speedup absoluto vs seq_prof(1 thread)
        if Npoints in seq_baseline:
            speedup_abs = seq_baseline[Npoints] / st["time_mean_s"]
        else:
            speedup_abs = math.nan

        # eficiência paralela interna (só faz sentido comparar a versão consigo mesma)
        # E_impl(T) = [T_impl(1) / T_impl(T)] / T
        impl_base_key = (impl, Npoints, 1)
        if impl_base_key in base_stats:
            t_base_impl = base_stats[impl_base_key]["time_mean_s"]
            speedup_internal = t_base_impl / st["time_mean_s"]
            efficiency = speedup_internal / threads
        else:
            speedup_internal = math.nan
            efficiency = math.nan

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
                "speedup_internal": speedup_internal,
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
                "speedup_internal",
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
                    r["speedup_internal"],
                    r["efficiency"],
                ]
            )
    print(f"Saved summary -> {path}")


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
        if r["impl"] == "seq_prof":
            continue  # não plotar a própria linha seq_prof
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
        if r["impl"] == "seq_prof":
            continue  # não plotar a própria linha seq_prof
        per_N.setdefault(r["Npoints"], {}).setdefault(r["impl"], []).append(r)

    for Npoints, impl_map in per_N.items():
        plt.figure()
        for impl, rows in impl_map.items():
            rows_sorted = sorted(rows, key=lambda x: x["threads"])
            x = [rr["threads"] for rr in rows_sorted]
            y = [rr["speedup_internal"] for rr in rows_sorted]
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
            if r["impl"] == "seq_prof":
                continue  # não queremos o sequencial aqui
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
    compile_all()

    raw_rows = collect_all_runs()
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
