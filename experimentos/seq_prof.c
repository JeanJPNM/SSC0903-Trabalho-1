/* montecarloLivro.c
    Implementação sequencial simples para estimar pi por Monte Carlo.
    Utiliza a função drand48_r e inclui medição de tempo de execução.
    Compilar: gcc montecarloLivro.c -o montecarloLivro -fopenmp
    Observação: a flag -fopenmp será utilizada para aproveitar o recurso de
    cronômetro da biblioteca.
    Uso: ./montecarloLivro (o número de pontos será pedido no console)
*/

#include <math.h>
#include <stdio.h>
#include <stdlib.h> // Para drand48_r, drand48_data, srand48_r, geração reentrante de números aleatórios entre 0 e 1 em ponto flutuante
#include <omp.h> // Para omp_get_wtime()
#include <time.h> // Para time()

int main(int argc, char **argv)
{
    long int count; // Pontos dentro do círculo
    long int i; // Contador
    double x, y; // Coordenadas do ponto

    // Variáveis para medir o tempo
    double start_time, end_time, wall_clock_time;

    // Estrutura para o estado do gerador reentrante
    struct drand48_data randBuffer;

    if (argc < 3){
        fprintf(stderr,"uso: %s <N_amostras> <num_threads>\n", argv[0]);
        return 1;
    }

		long int n = strtoull(argv[1], NULL, 10);
    // num_threads passado mas não usado de fato:
    // int num_threads = atoi(argv[2]);

    //inicializa o contador
    count = 0;

    // Inicializa o estado do gerador reentrante com a semente.
    srand48_r(time(NULL), &randBuffer);

    // --- Início da medição de tempo ---
    start_time = omp_get_wtime();

    for (i = 0; i < n; i++) {
        // Gera números aleatórios entre 0 e 1 usando drand48
        drand48_r(&randBuffer, &x);
        drand48_r(&randBuffer, &y);

        if (x * x + y * y <= 1) {
            count++;
        }
    }

    // --- Fim da medição de tempo ---
    end_time = omp_get_wtime();
    wall_clock_time = end_time - start_time;

    double long pi = ((double)count / (double)n) * 4.0L;

    printf("seq_prof,%lu,%d,%.9f,%.12Lf,%.12f\n",
               (long int)n,
               1, // threads efetivos
               wall_clock_time,
               pi,
               fabs(pi - M_PI));

    return 0;
}
