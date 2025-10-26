#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <unistd.h>
#include <time.h>
#include <math.h>
#include <omp.h>

// Constantes distintas para gerar x e y a partir de (s_thread, i)
//
// São utilizadas para garantir a construção de streams independentes por thread,
// por célula i e por coordenada (x e y).
//
// Essas constantes foram escolhidas arbritrariamente por serem conhecidas na literatura
// como boas constantes de domínio. Outras constantes poderiam ter sido escolhidas desde
// que fossem ímpares, grandes e distintas.
//
// Para a coordenada y, ainda se utilizou uma constante adicional 0xdeadbeefcafebabeULL
// para criar mais uma camada de separação de domínio.
#define C1 0x9e3779b97f4a7c15ULL
#define C2 0x94d049bb133111ebULL

/* @brief Gerador de números aleatórios
 *
 * @param x Estado do gerador
 *
 * @return Número aleatório gerado
 *
 * Inspirado no gerador de números aleatórios de 64-bits de estados descrito no
 * artigo "Fast splittable pseudorandom number generators" (2014) e na
 * implementação referência de Sebastiano Vigna (https://xoshiro.di.unimi.it/splitmix64.c).
 *
 * Essa função é thread-safe: não mantém ou acessa estado global.
 */
static inline uint64_t splitmix64(uint64_t x)
{
    x += 0x9e3779b97f4a7c15ULL;
    x = (x ^ (x >> 30)) * 0xbf58476d1ce4e5b9ULL;
    x = (x ^ (x >> 27)) * 0x94d049bb133111ebULL;
    return x ^ (x >> 31);
}

/* @brief Converte um inteiro de 64 bits em um double entre [0,1).
 *
 * @param u Inteiro sem sinal de 64 bits (entrada bruta de um PRNG).
 *
 * @return Um double uniformemente distribuído em [0,1), sob a hipótese de que
 * os 64 bits de `u` sejam indistinguíveis de aleatórios.
 *
 * Um double IEEE-754 possui 53 bits de precisão (52 de mantissa + 1 bit
 * implícito). Para gerar valores uniformes em [0,1), utiliza-se exatamente 53
 * bits do inteiro de entrada, garantindo todos os "subintervalos" representáveis
 * com o mesmo peso. O shift à direita por 11 posições (`u >> 11`) descarta os
 * 11 bits menos significativos, produzindo um inteiro em [0, 2^53 - 1]. Em
 * seguida, o valor é escalonado por 2^-53 (= 1.0 / 9007199254740992.0), obtendo
 * um double em [0,1).
 *
 * Essa função é thread-safe: não mantém ou acessa estado global.
 */
static inline double u01_from_u64(uint64_t u)
{
    return (double)(u >> 11) * (1.0/9007199254740992.0);
}

int main(int argc, char *argv[])
{
    double start, end, wall_clock_time;

    if (argc < 3){
        fprintf(stderr,"uso: %s <N_amostras> <num_threads>\n", argv[0]);
        return 1;
    }

    unsigned long n = strtoull(argv[1], NULL, 10);
    int num_threads = atoi(argv[2]);

    num_threads = 1;

    // Geração de uma seed inicial
    uint64_t base_seed = splitmix64(((uint64_t)time(NULL) << 32) ^ (uint64_t)getpid());

    unsigned long hits = 0ULL;

    start = omp_get_wtime();

    // Escolhe S tal que 2 * S * S <= n (duas amostras por célula com antitético)
    unsigned long S = (unsigned long) sqrtl(((long double)n) / 2.0);
    unsigned long n_strata = S * S;

    // Número de pontos usados na partição principal
    unsigned long n_used = 2ULL * n_strata;

    // Os pontos restantes vão para a partição residual
    unsigned long n_tail = n - n_used;

    // Parte 1: Partição Principal (Estratificação + Antitético)
    // Paralelizamos por linha (iy) entre as threads e vetorizamos por coluna (ix) com operações SIMD
    {
        int tid = 0;

        // Cada thread tem uma seed única
        uint64_t s_thread = splitmix64(base_seed ^ (uint64_t)(tid + 1));

        for (unsigned long iy = 0; iy < S; iy++) {

            unsigned long row = iy * S;

            // Acumulador parcial desta linha, que será atualizado vetorialmente
            unsigned long line_hits = 0ULL;

            for (unsigned long ix = 0; ix < S; ix++) {
                unsigned long i = row + ix;

                // Inteiros pseudoaleatórios de 64 bits usados para gerar as coordenadas x e y
                uint64_t ux = splitmix64(s_thread ^ (i * C1));
                uint64_t uy = splitmix64((s_thread ^ 0xdeadbeefcafebabeULL) ^ (i * C2));

                // Jitter independente dentro da célula
                double rx = u01_from_u64(ux);
                double ry = u01_from_u64(uy);

                // Ponto amostrado dentro da célula
                double x = ((double)ix + rx) / (double)S;
                double y = ((double)iy + ry) / (double)S;

                // Ponto direto
                double radius2 = x * x + y * y;

                // Antitético (1-x, 1-y): mesma célula “espelhada”
                double xa = 1.0 - x, ya = 1.0 - y;
                double radius2a = xa * xa + ya * ya;

                // Soma das duas contribuições
                unsigned long new_hits = (radius2 <= 1.0) + (radius2a <= 1.0);
                line_hits += new_hits;
            }

            hits += line_hits;
        }

        // Parte 2: Partição Residual
        // Monte Carlo “puro” sem particionamento por células
        for (unsigned long k = 0; k < n_tail; k++)
        {
            unsigned long i = n_strata + k;

            uint64_t ux = splitmix64(s_thread ^ (i * C1));
            uint64_t uy = splitmix64((s_thread ^ 0xdeadbeefcafebabeULL) ^ (i * C2));

            double x = u01_from_u64(ux);
            double y = u01_from_u64(uy);

            double radius2 = x * x + y * y;
            hits += (radius2 <= 1.0);
        }
    }

    end = omp_get_wtime();

    long double pi = 4.0L * (long double)hits/(long double)n;
    wall_clock_time = end - start;

    printf("codigo_novec,%lu,%d,%.9f,%.12Lf,%.12f\n",
           (unsigned long)n,
           num_threads,
           wall_clock_time,
           pi,
           fabs(pi - M_PI));

    return 0;
}
