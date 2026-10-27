// MT19937 bit-idêntico ao random.Random do CPython (Fase 5, Degrau 1).
//
// Réplica fiel do gerador do CPython (Modules/_randommodule.c +
// Lib/random.py), que é o domínio de RNG oficial do motor
// (DEGRAU1-DESIGN §3.3):
//   - semeadura por init_by_array (chave = |seed| em palavras de
//     32 bits, little-endian; seed 0 -> chave [0]);
//   - random() = genrand_res53: (a>>5)*2^26 + (b>>6), vezes 2^-53;
//   - getrandbits(k<=32) = genrand_uint32() >> (32-k);
//   - _randbelow(n) por rejeição sobre getrandbits(n.bit_length());
//   - uniform(a,b) = a + (b-a)*random();
//   - gauss(mu,sigma) com o algoritmo e o CACHE (gauss_next) do
//     CPython — o cache faz parte do estado serializável;
//   - lognormvariate(mu,sigma) = exp(gauss(mu,sigma));
//   - choice(seq) = seq[_randbelow(len)]; shuffle Fisher-Yates do
//     CPython (i decrescente, j = _randbelow(i+1)).
// Sem contração FMA: o chamador compila com -ffp-contract=off e as
// expressões aqui são escritas para não fundir mul+add.
#pragma once

#include <cmath>
#include <cstdint>
#include <vector>

namespace mundo_native {

class PyRandom {
  public:
    static constexpr int N = 624;
    static constexpr int M = 397;

    PyRandom() { seed_from_int(0); }

    // CPython: Random.seed(int) -> init_by_array com |seed| fatiado.
    void seed_from_int(int64_t seed) {
        uint64_t v = seed < 0 ? uint64_t(-(seed + 1)) + 1 : uint64_t(seed);
        std::vector<uint32_t> key;
        if (v == 0) key.push_back(0);
        while (v > 0) {
            key.push_back(uint32_t(v & 0xFFFFFFFFu));
            v >>= 32;
        }
        init_by_array(key);
    }

    void init_genrand(uint32_t s) {
        mt_[0] = s;
        for (int i = 1; i < N; ++i) {
            mt_[i] = 1812433253u * (mt_[i - 1] ^ (mt_[i - 1] >> 30))
                     + uint32_t(i);
        }
        index_ = N;
    }

    void init_by_array(const std::vector<uint32_t>& key) {
        init_genrand(19650218u);
        int i = 1, j = 0;
        int k = N > int(key.size()) ? N : int(key.size());
        for (; k > 0; --k) {
            mt_[i] = (mt_[i] ^ ((mt_[i - 1] ^ (mt_[i - 1] >> 30)) * 1664525u))
                     + key[j] + uint32_t(j);
            ++i;
            ++j;
            if (i >= N) { mt_[0] = mt_[N - 1]; i = 1; }
            if (j >= int(key.size())) j = 0;
        }
        for (k = N - 1; k > 0; --k) {
            mt_[i] = (mt_[i] ^ ((mt_[i - 1] ^ (mt_[i - 1] >> 30))
                                * 1566083941u))
                     - uint32_t(i);
            ++i;
            if (i >= N) { mt_[0] = mt_[N - 1]; i = 1; }
        }
        mt_[0] = 0x80000000u;
        index_ = N;
        has_gauss_ = false;
        gauss_next_ = 0.0;
    }

    uint32_t genrand_uint32() {
        if (index_ >= N) twist();
        uint32_t y = mt_[index_++];
        y ^= y >> 11;
        y ^= (y << 7) & 0x9D2C5680u;
        y ^= (y << 15) & 0xEFC60000u;
        y ^= y >> 18;
        return y;
    }

    // random.Random.random(): genrand_res53
    double random() {
        uint32_t a = genrand_uint32() >> 5;
        uint32_t b = genrand_uint32() >> 6;
        return (a * 67108864.0 + b) * (1.0 / 9007199254740992.0);
    }

    uint32_t getrandbits32(int k) {  // 1 <= k <= 32
        return genrand_uint32() >> (32 - k);
    }

    // _randbelow_with_getrandbits
    int64_t randbelow(int64_t n) {
        if (n <= 0) return 0;
        int k = 0;
        for (int64_t t = n; t > 0; t >>= 1) ++k;   // n.bit_length()
        int64_t r = getrandbits32(k);
        while (r >= n) r = getrandbits32(k);
        return r;
    }

    double uniform(double a, double b) { return a + (b - a) * random(); }

    // random.gauss do CPython (Lib/random.py), com cache gauss_next.
    double gauss(double mu, double sigma) {
        double z;
        if (has_gauss_) {
            z = gauss_next_;
            has_gauss_ = false;
        } else {
            double x2pi = random() * 6.283185307179586;   // TWOPI
            double g2rad = std::sqrt(-2.0 * std::log(1.0 - random()));
            z = std::cos(x2pi) * g2rad;
            gauss_next_ = std::sin(x2pi) * g2rad;
            has_gauss_ = true;
        }
        return mu + z * sigma;
    }

    // random.normalvariate do CPython (Kinderman-Monahan) — o
    // lognormvariate do 3.12 chama normalvariate, NÃO gauss (sem
    // cache; consome random() em laço de rejeição).
    double normalvariate(double mu, double sigma) {
        static const double NV_MAGICCONST =
            4.0 * std::exp(-0.5) / std::sqrt(2.0);
        while (true) {
            double u1 = random();
            double u2 = 1.0 - random();
            double z = NV_MAGICCONST * (u1 - 0.5) / u2;
            double zz = z * z / 4.0;
            if (zz <= -std::log(u2)) return mu + z * sigma;
        }
    }

    double lognormvariate(double mu, double sigma) {
        return std::exp(normalvariate(mu, sigma));
    }

    int64_t choice_index(int64_t n) { return randbelow(n); }

    template <typename T>
    void shuffle(std::vector<T>& x) {
        for (int64_t i = int64_t(x.size()) - 1; i >= 1; --i) {
            int64_t j = randbelow(i + 1);
            std::swap(x[size_t(i)], x[size_t(j)]);
        }
    }

    // getstate()/setstate() do CPython: (3, (624 palavras..., índice),
    // gauss_next|None). O vetor de estado tem 625 inteiros.
    std::vector<uint32_t> state_words() const {
        std::vector<uint32_t> out(mt_, mt_ + N);
        out.push_back(uint32_t(index_));
        return out;
    }
    void set_state(const std::vector<uint32_t>& words625, bool has_gauss,
                   double gauss_next) {
        for (int i = 0; i < N; ++i) mt_[i] = words625[size_t(i)];
        index_ = int(words625[N]);
        has_gauss_ = has_gauss;
        gauss_next_ = gauss_next;
    }
    bool has_gauss() const { return has_gauss_; }
    double gauss_next() const { return gauss_next_; }

  private:
    void twist() {
        for (int i = 0; i < N; ++i) {
            uint32_t y = (mt_[i] & 0x80000000u)
                         | (mt_[(i + 1) % N] & 0x7FFFFFFFu);
            uint32_t x = mt_[(i + M) % N] ^ (y >> 1);
            if (y & 1u) x ^= 0x9908B0DFu;
            mt_[i] = x;
        }
        index_ = 0;
    }

    uint32_t mt_[N];
    int index_ = N;
    bool has_gauss_ = false;
    double gauss_next_ = 0.0;
};

// Somação compensada de Neumaier — o sum() de floats do CPython >= 3.12
// (float_sum em Objects/floatobject.c via _Py_dg_stdnan-free fast path).
// É o terceiro ingrediente da paridade (DEGRAU1-DESIGN §3.3, achado do
// Portão 0): somas ingênuas divergem ~1 ulp nos totais do mercado.
inline double neumaier_sum(const double* xs, size_t n) {
    double result = 0.0, c = 0.0;
    for (size_t i = 0; i < n; ++i) {
        double x = xs[i];
        double t = result + x;
        if (std::fabs(result) >= std::fabs(x))
            c += (result - t) + x;
        else
            c += (x - t) + result;
        result = t;
    }
    return result + c;
}

template <typename It>
inline double neumaier_sum_it(It first, It last) {
    double result = 0.0, c = 0.0;
    for (It it = first; it != last; ++it) {
        double x = *it;
        double t = result + x;
        if (std::fabs(result) >= std::fabs(x))
            c += (result - t) + x;
        else
            c += (x - t) + result;
        result = t;
    }
    return result + c;
}

}  // namespace mundo_native
