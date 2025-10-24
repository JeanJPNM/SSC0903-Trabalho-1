/* montecarloParallel.c
    Implementação paralela para estimar pi por Monte Carlo com openMP.
    Compilar: gcc montecarloParallel.c -o montecarloParallel
*/

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <omp.h>
#include <time.h>

int main(int argc, char *argv[])
{
    long int count = 0;
    double start, end, wall_clock_time;

    if (argc < 3){
        fprintf(stderr,"uso: %s <N_amostras> <num_threads>\n", argv[0]);
        return 1;
    }

		long int n = strtoull(argv[1], NULL, 10);
    int num_threads = atoi(argv[2]);
    if (num_threads <= 0)
        num_threads = 1;

		omp_set_num_threads(num_threads);

    start = omp_get_wtime();

    #pragma omp parallel
    {
        long int local_count = 0;
        struct drand48_data randBuffer;
        double x, y;

        srand48_r(time(NULL) + omp_get_thread_num(), &randBuffer);

        #pragma omp for
        for(long int i = 0; i < n; ++i) {
            drand48_r(&randBuffer, &x);
            drand48_r(&randBuffer, &y);

            if(x * x + y * y <= 1.0) {
                local_count++;  // Count points inside the circle
            }
        }

        #pragma omp atomic
        count += local_count;
    }

    end = omp_get_wtime(); // Record the end time

    long double pi = (long double)count / n * 4; // Estimate of Pi

    printf("par_prof,%llu,%d,%.9f,%.12Lf,%.12f\n",
           (unsigned long long)n,
           num_threads,
           end - start,
           pi,
           fabs(pi - M_PI));

    return 0;
}
