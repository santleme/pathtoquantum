// Núcleo nativo do motor do Mundo Autônomo — Fase 5 do Degrau 1.
//
// Segunda implementação do step() do motor Python (src/mundo/engine.py),
// bit-idêntica por construção (DEGRAU1-DESIGN §3.2/§3.3/§3.5):
//   - RNG MT19937 réplica do CPython (mt19937.hpp), gauss com cache;
//   - sum() do CPython >= 3.12 replicado (Neumaier) onde o motor usa
//     sum() sobre floats; somas sequenciais comuns onde ele usa +=;
//   - ordem de iteração de dicts do Python replicada (ordem de
//     inserção) nas estruturas que afetam RNG, somas ou eventos;
//   - compilado com -O2 -ffp-contract=off -fno-fast-math, sem
//     -march=native: mesma ordem de operações IEEE-754 do CPython,
//     que chama a libm do sistema (exp/log/pow/sin/cos idênticos).
// O núcleo NÃO narra: emite registros de evento estruturados e a
// camada Python (mundo/native_engine.py) formata a Crônica com os
// mesmos templates do motor de referência — nenhuma string de
// narrativa nasce aqui, só os valores que a alimentam.
#include <nanobind/nanobind.h>
#include <nanobind/stl/string.h>
#include <nanobind/stl/vector.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <map>
#include <optional>
#include <set>
#include <string>
#include <utility>
#include <vector>

#include "mt19937.hpp"

namespace nb = nanobind;

// std::string -> objeto str do Python (chaves de dict nanobind)
inline nb::object pystr(const std::string& s) {
    return nb::steal<nb::object>(
        PyUnicode_FromStringAndSize(s.data(), Py_ssize_t(s.size())));
}
using mundo_native::PyRandom;
using mundo_native::neumaier_sum_it;

namespace {

// ------------------------------------------------------------------ //
// Constantes da cadeia (mundo/chain.py) — DADO congelado do motor.   //
// ------------------------------------------------------------------ //
constexpr int NC = 11;  // commodities
// chain.COMMODITIES (ordem de BASE_PRICES):
// 0 lithium_ore, 1 copper_ore, 2 iron_ore, 3 oil, 4 lithium,
// 5 copper, 6 iron, 7 plastic, 8 component, 9 device, 10 supercomputer
const std::array<const char*, NC> COMM_NAMES = {
    "lithium_ore", "copper_ore", "iron_ore", "oil", "lithium", "copper",
    "iron", "plastic", "component", "device", "supercomputer"};
const std::array<double, NC> BASE_PRICES = {
    900.0, 300.0, 110.0, 420.0, 12000.0, 9000.0, 700.0, 1200.0,
    2800.0, 9500.0, 1200000.0};
const std::array<double, NC> CITY_DEMAND = {
    0.0, 0.0, 0.0, 0.0, 90.0, 220.0, 600.0, 120.0, 260.0, 420.0, 7.0};
// RAW_TO_REFINED na ordem do dict literal de chain.py
constexpr int RAW_ORD[4] = {0, 1, 2, 3};        // lithium_ore..oil
constexpr int REFINED_OF[4] = {4, 5, 6, 7};     // lithium..plastic
constexpr int REFINED_OF_RAW[NC] = {4, 5, 6, 7, -1, -1, -1, -1, -1, -1, -1};
// commodities em ordem ordenada de nome (sorted(chain.COMMODITIES))
constexpr int SORTED_IDX[NC] = {8, 5, 1, 9, 6, 2, 4, 0, 3, 7, 10};
constexpr double REFINE_YIELD = 0.6;

// Instalações: 0 mine, 1 refinery, 2 factory, 3 plant, 4 assembly
const std::array<const char*, 5> FAC_NAMES = {"mine", "refinery", "factory",
                                              "plant", "assembly"};
const std::array<double, 5> FAC_COST = {2500000.0, 4000000.0, 6000000.0,
                                        8000000.0, 15000000.0};
const std::array<double, 5> FAC_CAPACITY = {420.0, 320.0, 300.0, 130.0, 2.0};
const std::array<double, 5> FAC_OPCOST = {42.0, 130.0, 300.0, 900.0, 60000.0};
constexpr double CLAIM_COST = 200000.0;
constexpr double PROBE_COST = 150000.0;

// Receitas (factory->component, plant->device, assembly->supercomputer)
// pares (índice do insumo, quantidade por unidade), ordem do dict.
struct RecipeIn { int idx; double per; };
const std::array<std::vector<RecipeIn>, 5> RECIPES = {
    std::vector<RecipeIn>{},
    std::vector<RecipeIn>{},
    std::vector<RecipeIn>{{5, 0.020}, {4, 0.005}},              // component
    std::vector<RecipeIn>{{8, 2.0}, {6, 0.050}, {7, 0.020}},    // device
    std::vector<RecipeIn>{{9, 10.0}, {8, 5.0}},                 // supercomputer
};
constexpr int PRODUCT_OF[5] = {-1, -1, 8, 9, 10};

// Ordem ordenada das commodities (sorted(chain.COMMODITIES))
const std::array<int, NC> COMM_SORTED = {8, 5, 1, 9, 6, 2, 4, 0, 3, 7, 10};
// Durações de regime por nome de regime (B1)
enum Regime : int { REG_NORMAL = 0, REG_BOOM = 1, REG_BUST = 2 };
const char* REGIME_NAMES[3] = {"normal", "boom", "bust"};

// Mundo embutido (world.py) — usado SÓ pela resolução nome->país do
// countrydata (vizinho mais próximo sobre os pontos do mundo builtin).
struct KnownPoint { double lat, lon; const char* country; };
const KnownPoint KNOWN_POINTS[] = {
    // depósitos builtin (ordem de world.DEPOSITS, só os com país no mapa)
    {-23.5, -68.2, "Chile"}, {-20.1, -67.5, "Bolívia"},
    {-24.2, -66.2, "Argentina"}, {-24.3, -69.1, "Chile"},
    {-22.3, -68.9, "Chile"}, {-17.3, -70.2, "Peru"},
    {-6.0, -50.3, "Brasil"}, {-20.0, -43.8, "Brasil"},
    {-24.8, -43.5, "Brasil"}, {-38.9, -68.6, "Argentina"},
    // cidades builtin (ordem de world.CITIES, idem)
    {-23.5, -46.6, "Brasil"}, {-22.9, -43.2, "Brasil"},
    {-34.6, -58.4, "Argentina"}, {-33.4, -70.7, "Chile"},
    {-12.0, -77.0, "Peru"}, {4.7, -74.1, "Colômbia"},
    {-19.9, -43.9, "Brasil"}, {-30.0, -51.2, "Brasil"},
};
const std::map<std::string, std::string> DEPOSIT_COUNTRIES = {
    {"Salar de Atacama", "Chile"}, {"Salar de Uyuni", "Bolívia"},
    {"Salinas de Jujuy", "Argentina"},
    {"Escondida (Norte do Chile)", "Chile"}, {"Chuquicamata", "Chile"},
    {"Sul do Peru (Toquepala)", "Peru"}, {"Carajás", "Brasil"},
    {"Quadrilátero Ferrífero", "Brasil"},
    {"Pré-sal (Bacia de Santos)", "Brasil"}, {"Vaca Muerta", "Argentina"},
    {"Salar del Hombre Muerto", "Argentina"},
    {"Cerro Verde (Arequipa)", "Peru"}, {"El Mutún", "Bolívia"},
};
const std::map<std::string, std::string> CITY_COUNTRIES = {
    {"São Paulo", "Brasil"}, {"Rio de Janeiro", "Brasil"},
    {"Belo Horizonte", "Brasil"}, {"Porto Alegre", "Brasil"},
    {"Buenos Aires", "Argentina"}, {"Santiago", "Chile"},
    {"Lima", "Peru"}, {"Bogotá", "Colômbia"}, {"Montevidéu", "Uruguai"},
    {"Assunção", "Paraguai"}, {"Medellín", "Colômbia"},
};

// Nomes/arquetipos de companies.py (make_companies)
const std::array<const char*, 8> COMP_NAMES = {
    "Andina Prime", "Vetor Sul", "Cuprum Andes", "Ferra Brasil",
    "Lítio Austral", "Nexo Indústrias", "PetroPlata", "Órbita Systems"};
struct Archetype { const char* name; double aggr, risk, vert, mkt; };
const std::array<Archetype, 8> ARCHETYPES = {{
    {"Agressiva", 0.90, 0.80, 0.40, 0.50},
    {"Verticalizadora", 0.50, 0.45, 0.95, 0.25},
    {"Marqueteira", 0.55, 0.50, 0.35, 0.95},
    {"Cautelosa", 0.30, 0.20, 0.60, 0.30},
    {"Expansionista", 0.80, 0.65, 0.55, 0.40},
    {"Oportunista", 0.65, 0.85, 0.30, 0.60},
    {"Industrial", 0.45, 0.40, 0.80, 0.20},
    {"Visionária", 0.60, 0.70, 0.70, 0.70},
}};
const std::array<const char*, 8> PALETTE = {
    "#e63946", "#f4a261", "#2a9d8f", "#457b9d",
    "#9b5de5", "#f15bb5", "#00bbf9", "#8ac926"};
constexpr double START_CASH = 40000000.0;

// Ferramentas (tools_sim.py)
constexpr int INSTA_DURATION = 3, ZAP_DURATION = 2;
constexpr int VID_DURATION = 6, LOJA_DURATION = 6;
constexpr double VID_DEMAND_WEIGHT = 2.8, LOJA_DEMAND_WEIGHT = 1.6;
constexpr double LOJA_FEE_PCT = 0.13;

int comm_index(const std::string& name) {
    for (int i = 0; i < NC; ++i)
        if (name == COMM_NAMES[i]) return i;
    throw nb::value_error(("commodity desconhecida: " + name).c_str());
}
int fac_index(const std::string& name) {
    for (int i = 0; i < 5; ++i)
        if (name == FAC_NAMES[i]) return i;
    throw nb::value_error(("instalação desconhecida: " + name).c_str());
}

// int() do Python sobre float: trunca para zero (como o cast C++).
inline int64_t py_int(double x) { return int64_t(x); }
// % do Python para inteiros (módulo com piso; divisor > 0 aqui).
inline int64_t py_mod(int64_t a, int64_t b) {
    int64_t r = a % b;
    return r < 0 ? r + b : r;
}
// round() do Python sem ndigits: nearest, ties-to-even sobre o valor
// binário exato — std::rint com o modo de arredondamento padrão
// (FE_TONEAREST) é exatamente isso.
inline int64_t py_round(double x) { return int64_t(std::rint(x)); }

double dget(const nb::dict& d, const char* key, double dflt) {
    if (!d.contains(key)) return dflt;
    nb::handle h = d[key];
    if (h.is_none()) return dflt;
    return nb::cast<double>(h);
}
int64_t iget(const nb::dict& d, const char* key, int64_t dflt) {
    if (!d.contains(key)) return dflt;
    nb::handle h = d[key];
    if (h.is_none()) return dflt;
    return nb::cast<int64_t>(h);
}
std::string sget(const nb::dict& d, const char* key,
                 const std::string& dflt = "") {
    if (!d.contains(key)) return dflt;
    nb::handle h = d[key];
    if (h.is_none()) return dflt;
    return nb::cast<std::string>(h);
}

// ------------------------------------------------------------------ //
// Parâmetros resolvidos (DADO; a camada Python resolve via          //
// marketdata/countrydata/equipdata e entrega dicts validados).     //
// ------------------------------------------------------------------ //
struct PolicyParams {
    double reserve_base, reserve_risk_span, mines_coef, dist_scale;
    double known_grade_base, size_ref, grade_thr_base, grade_thr_risk;
    double refinery_raw_trigger, factory_need_vertical;
    double factory_need_default, plant_component_trigger;
    double assembly_device_trigger, assembly_cash_cushion;
    double buy_budget_frac, buy_target_scale, buffer_scale;
    double insta_prob_scale, zap_prob_scale, pick_noise;
};

struct MarketComm {
    double elasticity, kappa, gamma, cover_target, sigma_monthly;
    double drift_boom, drift_bust, seasonal_amp;
    int64_t seasonal_phase;
    double dur[3];  // por regime: normal, boom, bust (meses médios)
};
struct MarketParams {
    std::array<MarketComm, NC> comm;
    double ema_alpha = 0.1;
    double band_lo = 0.25, band_hi = 6.0;
    int64_t record_window = 24;
    double record_min_break = 0.005, record_reversal = 0.05;
};

struct CountryModel {
    double capex_premium, local_opex_frac, s_reversion, s_sigma;
    double s_min, s_max, fx_beta, fx_min, fx_max, fx_reversion, fx_sigma;
    int64_t election_period, election_stagger;
    double election_smean_shift;
    std::vector<double> election_tau_steps;
    double tau_min, tau_max, smean_min, smean_max;
    double reform_hot_ratio, reform_tau_step, restriction_parity_surcharge;
    double jv_smean_drop, jv_tau_step, subsidy_tau_step, subsidy_smean_gain;
    double disaster_s_shock;
    int64_t restriction_months, halt_months_judicial, halt_months_disaster;
};
struct CountryParams {
    std::map<std::string, std::pair<double, double>> countries;  // S̄, tau
    CountryModel model;
    double ev_reform, ev_restriction, ev_jv, ev_halt, ev_subsidy, ev_disaster;
    double tariff, freight, capacity_factor, ore_scale, max_spread_mult;
};
struct ForceEvent {
    int64_t tick; std::string country, event, resource; bool has_resource;
};

struct EquipFac { double eta, beta, wear_rate; };
struct EquipParams {
    std::array<EquipFac, 5> fac;
    double age_derate, age_derate_months, hazard_scale, wear_scale;
    double repair_frac_min, repair_frac_max, repair_mu, repair_sigma;
    int64_t repair_ticks_min, repair_ticks_max;
    double maint_frac, maint_restore, maint_downtime_h, overhaul_frac;
    double pol_maint_h_base, pol_maint_h_care_span;
    double pol_repair_mult_care0, pol_repair_mult_care1;
    int64_t pol_overhaul_min_age;
    double pol_overhaul_max_cond;
};

struct GodEvent {
    int64_t tick; std::string type;
    int commodity = -1; double factor = 0, demand_factor = 1.0;
    int64_t duration = 6;
    // discovery
    std::string name; int resource = -1;
    double lat = 0, lon = 0, size_t = 0, grade = 0;
};

// ------------------------------------------------------------------ //
// Estado do mundo                                                    //
// ------------------------------------------------------------------ //
struct Deposit {
    std::string name; int resource; double lat, lon, size_t, grade;
    int cell_r, cell_c;
};
struct City {
    std::string name; double lat, lon, demand_weight;
    int cell_r, cell_c;
};
struct EquipState {
    bool present = false;
    int64_t age = 0; double cond = 1.0; int64_t down_until = -1;
    bool broken = false; double repair_cost = 0.0; int64_t repair_ticks = 0;
};
struct Facility {
    std::string id; int kind; int cell_r, cell_c;
    int deposit = -1;  // índice do depósito (kind == mine)
    EquipState equip;
};
struct Company {
    int cid = 0;
    std::string name, archetype, hq_city, color;
    double tr_aggr = 0, tr_risk = 0, tr_vert = 0, tr_mkt = 0;
    double cash = 0;
    std::array<double, NC> stocks{};
    std::vector<Facility> facilities;                 // ordem de inserção
    std::set<std::pair<int, int>> claimed;            // células
    std::map<std::string, std::pair<double, double>> knowledge;
    int64_t insta_until = -1; double insta_strength = 0.0;
    int64_t zap_until = -1, vid_until = -1, loja_until = -1;
    bool alive = true; int64_t founded_tick = 0; int64_t fac_n = 0;
    uint32_t kinds_mask = 0;
    std::array<double, NC> offers{}, buys{};
    std::map<std::string, std::pair<double, int64_t>> spend_hist;
};
struct Country {
    std::string name;
    double S, S_mean, fx, tau;
    int64_t halt_until = -1;
    std::map<std::string, int64_t> restrictions;  // recurso -> até tick
};
struct EquipStats {
    int64_t fac_ticks = 0, down_ticks = 0, breaks = 0;
    int64_t repairs = 0, maintenances = 0, overhauls = 0;
};
struct LedgerCell {
    double extracted = 0, produced = 0, consumed = 0, wasted = 0;
    double sold_external = 0, imported = 0;
};

std::pair<int, int> cell_of(double lat, double lon) {
    // world.cell_of: grade lat [-56,19], lon [-82,-27], célula 2,5°
    int r = int(py_int((lat + 56.0) / 2.5));
    int c = int(py_int((lon + 82.0) / 2.5));
    r = std::min(29, std::max(0, r));
    c = std::min(21, std::max(0, c));
    return {r, c};
}

std::string nearest_country(double lat, double lon) {
    std::string best;
    double best_dist = 0;
    bool first = true;
    for (const auto& p : KNOWN_POINTS) {
        double dist = std::fabs(lat - p.lat) + std::fabs(lon - p.lon);
        if (first || dist < best_dist) {
            best = p.country; best_dist = dist; first = false;
        }
    }
    return best;
}

}  // namespace

// ------------------------------------------------------------------ //
// O mundo: réplica do Engine + HeuristicPolicy do motor Python.     //
// ------------------------------------------------------------------ //
struct World {
    // configuração
    int64_t seed_ = 42;
    PyRandom rng;
    bool market_v2_ = false, country_v2_ = false, equip_v2_ = false;
    PolicyParams pol_;
    MarketParams mkt_;
    CountryParams ctry_;
    std::vector<ForceEvent> force_events_;
    EquipParams equip_;
    // estado
    int64_t tick_ = 0;
    std::vector<Deposit> deposits_;
    std::vector<City> cities_;
    std::vector<double> remaining_;
    std::map<std::pair<int, int>, int> claimed_by_;
    std::vector<Company> companies_;
    std::array<double, NC> prices_{}, anchors_{};
    std::map<int, std::pair<double, int64_t>> demand_factors_;
    std::vector<GodEvent> god_events_;
    std::map<int, std::string> first_link_;
    std::optional<int> cash_leader_, stage_leader_;
    std::vector<std::pair<int, double>> super_by_cid_;  // ordem de inserção
    std::array<LedgerCell, NC> ledger_{};
    double initial_cash_ = 0, money_in_ = 0, money_out_ = 0;
    double total_super_ = 0;
    int64_t bankruptcies_count_ = 0;
    double money_to_external_ = 0, money_from_external_ = 0;
    // B1
    std::array<int, NC> regime_{};
    std::array<int64_t, NC> regime_months_{};
    std::array<double, NC> demand_ema_{}, cover_{}, fair_noise_{};
    std::array<std::vector<double>, NC> price_ring_;
    std::array<int, NC> record_dir_{};       // -1 low, 0 none, 1 high
    std::array<double, NC> record_extreme_{};
    std::array<double, NC> tick_stock_totals_{}, tick_seasonal_{};
    // B3/B4a
    std::vector<Country> countries_;         // ordem ordenada de nomes
    std::map<std::string, size_t> country_idx_;
    std::map<std::string, std::string> dep_country_cache_;
    std::map<std::string, std::vector<int>> resources_cache_;
    bool resources_dirty_ = true;
    std::map<std::string, int64_t> election_offset_;
    std::map<int, double> parity_surcharge_;
    std::map<std::pair<std::string, double>, double> capex_memo_;
    std::map<int, double> royalty_due_;
    // B2
    std::vector<EquipStats> equip_stats_;
    // fluxos do tick (event-sourcing)
    std::vector<std::vector<std::pair<std::string, double>>> flows_;
    std::vector<double> cash_start_;

    explicit World(const nb::dict& cfg) { init(cfg); }
    World() = default;

    void init(const nb::dict& cfg);
    void parse_policy(const nb::dict& d) ;
    void parse_market(const nb::dict& d);
    void parse_country(const nb::dict& d);
    void parse_equip(const nb::dict& d);
    void make_companies(int n);
    void init_countries();
    void init_market();
    void init_equip();

    // consultas
    int city_idx(const std::string& name) const;
    int deposit_idx(const std::string& name) const;
    std::string deposit_country(const Deposit& dep);
    std::string city_country(const std::string& city_name);
    double capex_mult(const std::string& country);
    bool is_halted(const std::string& country) const;
    double demand_factor(int comm) const;
    const Country* country_by_name(const std::string& n) const;
    std::vector<int>& country_resources(const std::string& country);

    // primitivas
    void flow(int cid, const std::string& key, double amount);
    void spend(Company& c, double amount, const char* reason);
    void ops_spend(Company& c, const std::string& country, double amount);
    void convert(Company& c, int src, double qty_in, int dst, double qty_out);
    int chain_stage(const Company& c) const;
    bool has_kind(const Company& c, int kind) const;

    // eventos (narração é da camada Python)
    nb::list* ev_ = nullptr;
    void emit(const char* kind, const nb::object& company, nb::dict data,
              nb::dict fmt);
    void note_link(Company& c, int stage);

    // política (HeuristicPolicy)
    double reserve(const Company& c) const;
    void decide(Company& c);
    void maintain_equipment(Company& c);
    int pick_deposit(Company& c);   // índice do depósito ou -1
    bool build_downstream(Company& c, double spendable);
    void plan_buys(Company& c);
    double buffer(const Company& c, int comm) const;
    void plan_sells(Company& c);
    void use_tools(Company& c);

    // deus e ambiente
    void apply_god_events();
    void advance_market();
    void narrate_regime(int comm, int new_regime);
    void advance_politics();
    void apply_political_event(const std::string& country,
                               const std::string& event,
                               const std::optional<std::string>& resource);
    std::optional<std::string> hottest_resource(const std::string& country);
    bool reform_hot(const std::string& country);
    std::pair<double, double> parity(int comm) const;

    // equipamentos
    EquipState& fac_equip(Facility& f);
    bool facility_down(const Facility& f) const;
    void wear_and_roll(Company& c, Facility& f, double utilization);
    void break_facility(Company& c, Facility& f);
    void repair_facility(Company& c, Facility& f);
    void maintain_facility(Company& c, Facility& f);
    void overhaul_facility(Company& c, Facility& f);

    // produção e mercado
    void produce(Company& c);
    void market();
    void market_classic(int comm);
    void market_living(int comm);
    void trade_internal(int comm, double price,
                        const std::vector<std::pair<int, double>>& offers,
                        const std::vector<std::pair<int, double>>& buys,
                        std::map<int, double>& offered_left,
                        std::optional<std::map<int, double>>& received);
    double city_sales(int comm, double price, double city_q,
                      const std::vector<std::pair<int, double>>& offers,
                      std::map<int, double>& offered_left);
    std::pair<double, double> external_trade(
        int comm, const std::vector<std::pair<int, double>>& offers,
        std::map<int, double>& offered_left,
        const std::optional<std::vector<std::pair<int, double>>>&
            unfilled_buyers,
        double price, double city_unfilled);
    void note_price_record(int comm, double new_price,
                           const std::vector<double>& prev_ring);

    // falência, rivalidade, passo
    void check_bankruptcy(Company& c);
    std::string bankruptcy_cause(const Company& c) const;
    void note_rivalry();
    int leader(bool by_stage) const;   // cid ou -1 (entre vivas)
    void emit_flows();
    nb::list step();

    // exportação / importação de estado
    nb::dict export_companies() const;      // lista em "companies"
    nb::dict frame_data() const;
    nb::dict result_data() const;
    nb::dict full_state() const;
    void import_state(const nb::dict& st, const nb::dict& cfg_static);
};

int World::city_idx(const std::string& name) const {
    for (size_t i = 0; i < cities_.size(); ++i)
        if (cities_[i].name == name) return int(i);
    return -1;
}
int World::deposit_idx(const std::string& name) const {
    for (size_t i = 0; i < deposits_.size(); ++i)
        if (deposits_[i].name == name) return int(i);
    return -1;
}
bool World::has_kind(const Company& c, int kind) const {
    return (c.kinds_mask >> kind) & 1u;
}
int World::chain_stage(const Company& c) const {
    for (int s = 5; s >= 1; --s)
        if (has_kind(c, s - 1)) return s;
    return 0;
}
const Country* World::country_by_name(const std::string& n) const {
    auto it = country_idx_.find(n);
    return it == country_idx_.end() ? nullptr : &countries_[it->second];
}
bool World::is_halted(const std::string& country) const {
    const Country* st = country_by_name(country);
    return st != nullptr && tick_ <= st->halt_until;
}
double World::demand_factor(int comm) const {
    auto it = demand_factors_.find(comm);
    if (it != demand_factors_.end() && tick_ <= it->second.second)
        return it->second.first;
    return 1.0;
}

void World::emit(const char* kind, const nb::object& company, nb::dict data,
                 nb::dict fmt) {
    nb::dict e;
    e["kind"] = kind;
    e["tick"] = tick_;
    e["company"] = company;
    e["data"] = data;
    e["fmt"] = fmt;
    ev_->append(e);
}

void World::flow(int cid, const std::string& key, double amount) {
    auto& v = flows_[size_t(cid)];
    for (auto& kv : v)
        if (kv.first == key) { kv.second += amount; return; }
    v.emplace_back(key, amount);
}

void World::spend(Company& c, double amount, const char* reason) {
    c.cash -= amount;
    money_out_ += amount;
    flow(c.cid, std::string("spend_") + reason, -amount);
    c.spend_hist[reason] = {amount, tick_};
}

void World::convert(Company& c, int src, double qty_in, int dst,
                    double qty_out) {
    c.stocks[src] -= qty_in;
    c.stocks[dst] += qty_out;
    ledger_[src].consumed += qty_in;
    ledger_[src].wasted += std::max(0.0, qty_in - qty_out);
    ledger_[dst].produced += qty_out;
}

// ------------------------------------------------------------------ //
// Construção                                                         //
// ------------------------------------------------------------------ //
void World::parse_policy(const nb::dict& d) {
    pol_.reserve_base = dget(d, "reserve_base", 0);
    pol_.reserve_risk_span = dget(d, "reserve_risk_span", 0);
    pol_.mines_coef = dget(d, "mines_coef", 0);
    pol_.dist_scale = dget(d, "dist_scale", 0);
    pol_.known_grade_base = dget(d, "known_grade_base", 0);
    pol_.size_ref = dget(d, "size_ref", 0);
    pol_.grade_thr_base = dget(d, "grade_thr_base", 0);
    pol_.grade_thr_risk = dget(d, "grade_thr_risk", 0);
    pol_.refinery_raw_trigger = dget(d, "refinery_raw_trigger", 0);
    pol_.factory_need_vertical = dget(d, "factory_need_vertical", 0);
    pol_.factory_need_default = dget(d, "factory_need_default", 0);
    pol_.plant_component_trigger = dget(d, "plant_component_trigger", 0);
    pol_.assembly_device_trigger = dget(d, "assembly_device_trigger", 0);
    pol_.assembly_cash_cushion = dget(d, "assembly_cash_cushion", 0);
    pol_.buy_budget_frac = dget(d, "buy_budget_frac", 0);
    pol_.buy_target_scale = dget(d, "buy_target_scale", 0);
    pol_.buffer_scale = dget(d, "buffer_scale", 0);
    pol_.insta_prob_scale = dget(d, "insta_prob_scale", 0);
    pol_.zap_prob_scale = dget(d, "zap_prob_scale", 0);
    pol_.pick_noise = dget(d, "pick_noise", 0);
}

void World::parse_market(const nb::dict& d) {
    nb::dict comms = nb::cast<nb::dict>(d["commodities"]);
    for (int i = 0; i < NC; ++i) {
        nb::dict p = nb::cast<nb::dict>(comms[COMM_NAMES[i]]);
        MarketComm& mc = mkt_.comm[i];
        mc.elasticity = dget(p, "elasticity", 0);
        mc.kappa = dget(p, "kappa", 0);
        mc.gamma = dget(p, "gamma", 0);
        mc.cover_target = dget(p, "cover_target", 0);
        mc.sigma_monthly = dget(p, "sigma_monthly", 0);
        mc.drift_boom = dget(p, "drift_boom", 0);
        mc.drift_bust = dget(p, "drift_bust", 0);
        mc.seasonal_amp = dget(p, "seasonal_amp", 0);
        mc.seasonal_phase = iget(p, "seasonal_phase", 0);
        mc.dur[REG_NORMAL] = dget(p, "normal_months", 0);
        mc.dur[REG_BOOM] = dget(p, "boom_months", 0);
        mc.dur[REG_BUST] = dget(p, "bust_months", 0);
    }
    nb::dict model = nb::cast<nb::dict>(d["model"]);
    mkt_.ema_alpha = dget(model, "ema_alpha", 0.1);
    if (model.contains("price_band_of_anchor")) {
        nb::list band = nb::cast<nb::list>(model["price_band_of_anchor"]);
        mkt_.band_lo = nb::cast<double>(band[0]);
        mkt_.band_hi = nb::cast<double>(band[1]);
    }
    mkt_.record_window = iget(model, "record_window_months", 24);
    mkt_.record_min_break = dget(model, "record_min_break_pct", 0.005);
    mkt_.record_reversal = dget(model, "record_episode_reversal_pct", 0.05);
}

void World::parse_country(const nb::dict& d) {
    nb::dict cs = nb::cast<nb::dict>(d["countries"]);
    for (auto item : cs) {
        std::string name = nb::cast<std::string>(item.first);
        nb::dict p = nb::cast<nb::dict>(item.second);
        ctry_.countries[name] = {dget(p, "stability_mean", 0),
                                 dget(p, "royalty", 0)};
    }
    nb::dict m = nb::cast<nb::dict>(d["model"]);
    CountryModel& cm = ctry_.model;
    cm.capex_premium = dget(m, "capex_premium", 0);
    cm.local_opex_frac = dget(m, "local_opex_frac", 0);
    cm.s_reversion = dget(m, "s_reversion", 0);
    cm.s_sigma = dget(m, "s_sigma", 0);
    cm.s_min = dget(m, "s_min", 0);
    cm.s_max = dget(m, "s_max", 0);
    cm.fx_beta = dget(m, "fx_beta", 0);
    cm.fx_min = dget(m, "fx_min", 0);
    cm.fx_max = dget(m, "fx_max", 0);
    cm.fx_reversion = dget(m, "fx_reversion", 0);
    cm.fx_sigma = dget(m, "fx_sigma", 0);
    cm.election_period = iget(m, "election_period", 0);
    cm.election_stagger = iget(m, "election_stagger", 6);
    cm.election_smean_shift = dget(m, "election_smean_shift", 0);
    cm.election_tau_steps =
        nb::cast<std::vector<double>>(m["election_tau_steps"]);
    cm.tau_min = dget(m, "tau_min", 0);
    cm.tau_max = dget(m, "tau_max", 0);
    cm.smean_min = dget(m, "smean_min", 0);
    cm.smean_max = dget(m, "smean_max", 0);
    cm.reform_hot_ratio = dget(m, "reform_hot_ratio", 0);
    cm.reform_tau_step = dget(m, "reform_tau_step", 0);
    cm.restriction_parity_surcharge =
        dget(m, "restriction_parity_surcharge", 0);
    cm.jv_smean_drop = dget(m, "jv_smean_drop", 0);
    cm.jv_tau_step = dget(m, "jv_tau_step", 0);
    cm.subsidy_tau_step = dget(m, "subsidy_tau_step", 0);
    cm.subsidy_smean_gain = dget(m, "subsidy_smean_gain", 0);
    cm.disaster_s_shock = dget(m, "disaster_s_shock", 0);
    cm.restriction_months = iget(m, "restriction_months", 0);
    cm.halt_months_judicial = iget(m, "halt_months_judicial", 0);
    cm.halt_months_disaster = iget(m, "halt_months_disaster", 0);
    nb::dict ev = nb::cast<nb::dict>(d["events_yearly"]);
    ctry_.ev_reform = dget(ev, "royalty_reform", 0);
    ctry_.ev_restriction = dget(ev, "export_restriction", 0);
    ctry_.ev_jv = dget(ev, "state_jv", 0);
    ctry_.ev_halt = dget(ev, "judicial_halt", 0);
    ctry_.ev_subsidy = dget(ev, "subsidy", 0);
    ctry_.ev_disaster = dget(ev, "disaster", 0);
    nb::dict tr = nb::cast<nb::dict>(d["trade"]);
    ctry_.tariff = dget(tr, "tariff", 0);
    ctry_.freight = dget(tr, "freight", 0);
    ctry_.capacity_factor = dget(tr, "capacity_factor", 0);
    ctry_.ore_scale = dget(tr, "ore_scale", 0);
    ctry_.max_spread_mult = dget(tr, "max_spread_mult", 0);
    force_events_.clear();
    if (d.contains("force_events_norm")) {
        for (auto h : nb::cast<nb::list>(d["force_events_norm"])) {
            nb::dict fe = nb::cast<nb::dict>(h);
            ForceEvent e;
            e.tick = iget(fe, "tick", 0);
            e.country = sget(fe, "country");
            e.event = sget(fe, "event");
            e.has_resource = fe.contains("resource")
                             && !fe["resource"].is_none();
            e.resource = e.has_resource ? sget(fe, "resource") : "";
            force_events_.push_back(e);
        }
    }
}

void World::parse_equip(const nb::dict& d) {
    nb::dict facs = nb::cast<nb::dict>(d["facilities"]);
    for (int k = 0; k < 5; ++k) {
        nb::dict p = nb::cast<nb::dict>(facs[FAC_NAMES[k]]);
        equip_.fac[k] = {dget(p, "eta_months", 0), dget(p, "beta", 0),
                        dget(p, "wear_rate", 0)};
    }
    nb::dict m = nb::cast<nb::dict>(d["model"]);
    equip_.age_derate = dget(m, "age_derate", 0);
    equip_.age_derate_months = dget(m, "age_derate_months", 0);
    equip_.hazard_scale = dget(m, "hazard_scale", 0);
    equip_.wear_scale = dget(m, "wear_scale", 0);
    equip_.repair_frac_min = dget(m, "repair_frac_min", 0);
    equip_.repair_frac_max = dget(m, "repair_frac_max", 0);
    equip_.repair_mu = dget(m, "repair_ticks_lognorm_mu", 0);
    equip_.repair_sigma = dget(m, "repair_ticks_lognorm_sigma", 0);
    equip_.repair_ticks_min = iget(m, "repair_ticks_min", 0);
    equip_.repair_ticks_max = iget(m, "repair_ticks_max", 0);
    equip_.maint_frac = dget(m, "maint_frac", 0);
    equip_.maint_restore = dget(m, "maint_restore", 0);
    equip_.maint_downtime_h = dget(m, "maint_downtime_h", 0);
    equip_.overhaul_frac = dget(m, "overhaul_frac", 0);
    nb::dict pol = nb::cast<nb::dict>(d["policy"]);
    equip_.pol_maint_h_base = dget(pol, "maint_h_base", 0);
    equip_.pol_maint_h_care_span = dget(pol, "maint_h_care_span", 0);
    equip_.pol_repair_mult_care0 = dget(pol, "repair_mult_care0", 0);
    equip_.pol_repair_mult_care1 = dget(pol, "repair_mult_care1", 0);
    equip_.pol_overhaul_min_age = iget(pol, "overhaul_min_age", 0);
    equip_.pol_overhaul_max_cond = dget(pol, "overhaul_max_cond", 0);
}

void World::make_companies(int n) {
    std::vector<int64_t> order = {0, 1, 2, 3, 4, 5, 6, 7};
    rng.shuffle(order);
    companies_.clear();
    for (int i = 0; i < n; ++i) {
        int k = int(order[size_t(i % 8)]);
        const Archetype& a = ARCHETYPES[size_t(k % 8)];
        Company c;
        c.cid = i;
        c.name = COMP_NAMES[size_t(k)];
        c.archetype = a.name;
        c.tr_aggr = a.aggr; c.tr_risk = a.risk;
        c.tr_vert = a.vert; c.tr_mkt = a.mkt;
        c.hq_city = cities_[size_t(i) % cities_.size()].name;
        c.color = PALETTE[size_t(i % 8)];
        c.cash = START_CASH * rng.uniform(0.85, 1.2);
        companies_.push_back(std::move(c));
    }
}

void World::init_market() {
    for (int i = 0; i < NC; ++i) {
        regime_[i] = REG_NORMAL;
        regime_months_[i] = 0;
        demand_ema_[i] = std::max(CITY_DEMAND[i], 10.0);
        cover_[i] = 0.0;
        fair_noise_[i] = 0.0;
        price_ring_[i].clear();
        record_dir_[i] = 0;
        record_extreme_[i] = 0.0;
    }
}

void World::init_countries() {
    std::set<std::string> names;
    for (auto& d : deposits_) names.insert(deposit_country(d));
    for (auto& c : cities_) names.insert(city_country(c.name));
    countries_.clear();
    country_idx_.clear();
    for (const auto& name : names) {   // std::set: ordem ordenada
        auto it = ctry_.countries.find(name);
        Country st;
        st.name = name;
        st.S = it->second.first;
        st.S_mean = it->second.first;
        st.fx = 1.0;
        st.tau = it->second.second;
        st.halt_until = -1;
        country_idx_[name] = countries_.size();
        countries_.push_back(std::move(st));
    }
    election_offset_.clear();
    int64_t i = 0;
    for (const auto& st : countries_)
        election_offset_[st.name] = (i++) * ctry_.model.election_stagger;
}

void World::init_equip() {
    equip_stats_.assign(companies_.size(), EquipStats{});
}

void World::init(const nb::dict& cfg) {
    seed_ = iget(cfg, "seed", 42);
    rng.seed_from_int(seed_);
    tick_ = 0;
    for (auto h : nb::cast<nb::list>(cfg["deposits"])) {
        nb::dict d = nb::cast<nb::dict>(h);
        Deposit dep;
        dep.name = sget(d, "name");
        dep.resource = comm_index(sget(d, "resource"));
        dep.lat = dget(d, "lat", 0);
        dep.lon = dget(d, "lon", 0);
        dep.size_t = dget(d, "size_t", 0);
        dep.grade = dget(d, "grade", 0);
        auto cell = cell_of(dep.lat, dep.lon);
        dep.cell_r = cell.first; dep.cell_c = cell.second;
        deposits_.push_back(dep);
        remaining_.push_back(dep.size_t);
    }
    for (auto h : nb::cast<nb::list>(cfg["cities"])) {
        nb::dict d = nb::cast<nb::dict>(h);
        City c;
        c.name = sget(d, "name");
        c.lat = dget(d, "lat", 0);
        c.lon = dget(d, "lon", 0);
        c.demand_weight = dget(d, "demand_weight", 0);
        auto cell = cell_of(c.lat, c.lon);
        c.cell_r = cell.first; c.cell_c = cell.second;
        cities_.push_back(c);
    }
    for (auto h : nb::cast<nb::list>(cfg["god_events"])) {
        nb::dict e = nb::cast<nb::dict>(h);
        GodEvent g;
        g.tick = iget(e, "tick", 0);
        g.type = sget(e, "type");
        if (g.type == "price_shock") {
            g.commodity = comm_index(sget(e, "commodity"));
            g.factor = dget(e, "factor", 0);
            g.demand_factor = dget(e, "demand_factor", 1.0);
            g.duration = iget(e, "duration", 6);
        } else if (g.type == "discovery") {
            g.name = sget(e, "name");
            g.resource = comm_index(sget(e, "resource"));
            g.lat = dget(e, "lat", 0);
            g.lon = dget(e, "lon", 0);
            g.size_t = dget(e, "size_t", 0);
            g.grade = dget(e, "grade", 0);
        } else if (g.type == "sanction") {
            g.resource = comm_index(sget(e, "resource"));
            g.duration = iget(e, "duration", 6);
        }
        god_events_.push_back(g);
    }
    parse_policy(nb::cast<nb::dict>(cfg["policy_params"]));
    market_v2_ = nb::cast<bool>(cfg["market_v2"]);
    country_v2_ = nb::cast<bool>(cfg["country_v2"]);
    equip_v2_ = nb::cast<bool>(cfg["equip_v2"]);
    if (market_v2_) parse_market(nb::cast<nb::dict>(cfg["market_params"]));
    if (country_v2_) parse_country(nb::cast<nb::dict>(cfg["country_params"]));
    if (equip_v2_) parse_equip(nb::cast<nb::dict>(cfg["equip_params"]));
    prices_ = BASE_PRICES;
    anchors_ = BASE_PRICES;
    make_companies(int(iget(cfg, "n_companies", 8)));
    if (market_v2_) init_market();
    if (country_v2_) init_countries();
    if (equip_v2_) init_equip();
    {
        std::vector<double> cashes;
        for (auto& c : companies_) cashes.push_back(c.cash);
        initial_cash_ = neumaier_sum_it(cashes.begin(), cashes.end());
    }
    flows_.assign(companies_.size(), {});
    // valida sedes (Engine.__init__ levanta KeyError se a sede não existe)
    for (auto& c : companies_)
        if (city_idx(c.hq_city) < 0)
            throw nb::key_error(c.hq_city.c_str());
}

// ------------------------------------------------------------------ //
// Resolução de país (countrydata) e efeitos do B3                    //
// ------------------------------------------------------------------ //
std::string World::deposit_country(const Deposit& dep) {
    auto it = dep_country_cache_.find(dep.name);
    if (it != dep_country_cache_.end()) return it->second;
    std::string got;
    auto m = DEPOSIT_COUNTRIES.find(dep.name);
    if (m != DEPOSIT_COUNTRIES.end()) got = m->second;
    else got = nearest_country(dep.lat, dep.lon);
    dep_country_cache_[dep.name] = got;
    return got;
}

std::string World::city_country(const std::string& city_name) {
    auto m = CITY_COUNTRIES.find(city_name);
    if (m != CITY_COUNTRIES.end()) return m->second;
    int idx = city_idx(city_name);
    if (idx < 0) return "Brasil";
    return nearest_country(cities_[size_t(idx)].lat, cities_[size_t(idx)].lon);
}

double World::capex_mult(const std::string& country) {
    if (!country_v2_) return 1.0;
    const Country* st = country_by_name(country);
    if (st == nullptr) return 1.0;
    auto key = std::make_pair(country, st->S);
    auto it = capex_memo_.find(key);
    if (it != capex_memo_.end()) return it->second;
    double got = 1.0 + ctry_.model.capex_premium * (1.0 - st->S);
    capex_memo_[key] = got;
    return got;
}

void World::ops_spend(Company& c, const std::string& country, double amount) {
    if (!country_v2_) {
        spend(c, amount, "ops");
        return;
    }
    const Country& st = countries_[country_idx_[country]];
    double lam = ctry_.model.local_opex_frac;
    double eff = amount * ((1.0 - lam) + lam / st.fx);
    spend(c, eff, "ops");
    double royalty = eff * st.tau;
    if (royalty > 0.0) royalty_due_[c.cid] += royalty;
}

std::vector<int>& World::country_resources(const std::string& country) {
    if (resources_dirty_) {
        std::map<std::string, std::set<int>> by;
        for (auto& d : deposits_)
            by[deposit_country(d)].insert(d.resource);
        resources_cache_.clear();
        for (auto& kv : by) {
            std::vector<int> v(kv.second.begin(), kv.second.end());
            // o Python ordena os NOMES (sorted do set de strings) —
            // a ordem decide rng.choice e resources[0]
            std::sort(v.begin(), v.end(), [](int a, int b) {
                return std::string(COMM_NAMES[a]) < COMM_NAMES[b];
            });
            resources_cache_[kv.first] = std::move(v);
        }
        resources_dirty_ = false;
    }
    static std::vector<int> empty;
    auto it = resources_cache_.find(country);
    return it == resources_cache_.end() ? empty : it->second;
}

// ------------------------------------------------------------------ //
// Deus                                                               //
// ------------------------------------------------------------------ //
void World::apply_god_events() {
    for (const auto& ev : god_events_) {
        if (ev.tick != tick_) continue;
        if (ev.type == "price_shock") {
            prices_[ev.commodity] *= ev.factor;
            demand_factors_[ev.commodity] = {ev.demand_factor,
                                             tick_ + ev.duration};
            nb::dict fmt;
            fmt["commodity"] = COMM_NAMES[ev.commodity];
            fmt["factor"] = ev.factor;
            emit("god_shock", nb::none(), nb::dict(), fmt);
        } else if (ev.type == "discovery") {
            Deposit d;
            d.name = ev.name;
            d.resource = ev.resource;
            d.lat = ev.lat; d.lon = ev.lon;
            d.size_t = ev.size_t; d.grade = ev.grade;
            auto cell = cell_of(d.lat, d.lon);
            d.cell_r = cell.first; d.cell_c = cell.second;
            deposits_.push_back(d);
            remaining_.push_back(d.size_t);
            resources_dirty_ = true;
            nb::dict fmt;
            fmt["resource"] = COMM_NAMES[ev.resource];
            fmt["name"] = ev.name;
            emit("god_discovery", nb::none(), nb::dict(), fmt);
        } else if (ev.type == "sanction") {
            int64_t until = tick_ + ev.duration;
            demand_factors_[ev.resource] = {0.5, until};
            int refined = -1;
            for (int i = 0; i < 4; ++i)
                if (RAW_ORD[i] == ev.resource) refined = REFINED_OF[i];
            if (refined >= 0) demand_factors_[refined] = {0.5, until};
            nb::dict fmt;
            fmt["resource"] = COMM_NAMES[ev.resource];
            fmt["duration"] = ev.duration;
            emit("god_sanction", nb::none(), nb::dict(), fmt);
        }
    }
}

void World::note_link(Company& c, int stage) {
    if (stage < 1 || first_link_.count(stage)) return;
    first_link_[stage] = c.name;
    nb::dict data;
    data["stage"] = stage; data["era"] = 1;
    nb::dict fmt;
    fmt["name"] = c.name; fmt["stage"] = stage;
    emit("chain_link", nb::cast(c.name), data, fmt);
    nb::dict data2;
    data2["stage"] = stage; data2["era"] = 1; data2["record"] = "first_link";
    emit("record", nb::cast(c.name), data2, fmt);
}

// ------------------------------------------------------------------ //
// HeuristicPolicy (engine.py) — transcrição linha a linha.          //
// ------------------------------------------------------------------ //
double World::reserve(const Company& c) const {
    return pol_.reserve_base + (1.0 - c.tr_risk) * pol_.reserve_risk_span;
}

EquipState& World::fac_equip(Facility& f) {
    if (!f.equip.present) {
        f.equip.present = true;
        f.equip.age = 0; f.equip.cond = 1.0; f.equip.down_until = -1;
        f.equip.broken = false; f.equip.repair_cost = 0.0;
        f.equip.repair_ticks = 0;
    }
    return f.equip;
}

bool World::facility_down(const Facility& f) const {
    return f.equip.present && (f.equip.broken || tick_ <= f.equip.down_until);
}

void World::maintain_equipment(Company& c) {
    const auto& pol = equip_;
    double care = 1.0 - c.tr_aggr;
    double res = reserve(c);
    double maint_thr = pol.pol_maint_h_base + care * pol.pol_maint_h_care_span;
    double repair_mult = pol.pol_repair_mult_care0 + care * (
        pol.pol_repair_mult_care1 - pol.pol_repair_mult_care0);
    for (auto& fac : c.facilities) {
        EquipState& eq = fac_equip(fac);
        double build = FAC_COST[fac.kind];
        if (eq.broken) {
            if (c.cash - res > eq.repair_cost * repair_mult)
                repair_facility(c, fac);
            continue;
        }
        if (tick_ <= eq.down_until) continue;
        if (eq.age >= pol.pol_overhaul_min_age
                && eq.cond <= pol.pol_overhaul_max_cond) {
            if (c.cash - res > build * equip_.overhaul_frac)
                overhaul_facility(c, fac);
            continue;
        }
        if (eq.cond < maint_thr
                && c.cash - res > build * equip_.maint_frac)
            maintain_facility(c, fac);
    }
}

int World::pick_deposit(Company& c) {
    const City& hq = cities_[size_t(city_idx(c.hq_city))];
    std::set<std::string> mined;
    for (auto& f : c.facilities)
        if (f.deposit >= 0) mined.insert(deposits_[size_t(f.deposit)].name);
    int best = -1;
    double best_score = -1.0;
    for (size_t di = 0; di < deposits_.size(); ++di) {
        const Deposit& d = deposits_[di];
        auto own = claimed_by_.find({d.cell_r, d.cell_c});
        if (own != claimed_by_.end() && own->second != c.cid) continue;
        if (mined.count(d.name)) continue;
        double dist = std::fabs(d.lat - hq.lat) + std::fabs(d.lon - hq.lon);
        double score = BASE_PRICES[d.resource] / (1.0 + dist / pol_.dist_scale);
        auto known = c.knowledge.find(d.name);
        if (known != c.knowledge.end()) {
            score *= pol_.known_grade_base + known->second.first;
            score *= std::min(1.5, known->second.second / pol_.size_ref);
        }
        double noise = pol_.pick_noise;
        score *= rng.uniform(1.0 - noise, 1.0 + noise);
        if (score > best_score) { best = int(di); best_score = score; }
    }
    return best;
}

bool World::build_downstream(Company& c, double spendable) {
    const City& hq = cities_[size_t(city_idx(c.hq_city))];
    std::string country = city_country(c.hq_city);
    double mult = capex_mult(country);
    auto build = [&](int kind) {
        spend(c, FAC_COST[kind] * mult, "build");
        c.fac_n += 1;
        Facility f;
        f.id = "f" + std::to_string(c.cid) + "-" + std::to_string(c.fac_n);
        f.kind = kind;
        f.cell_r = hq.cell_r; f.cell_c = hq.cell_c;
        c.facilities.push_back(f);
        c.kinds_mask |= (1u << kind);
        nb::dict data;
        data["cid"] = c.cid; data["fid"] = f.id;
        data["facility_kind"] = FAC_NAMES[kind];
        nb::list cell; cell.append(f.cell_r); cell.append(f.cell_c);
        data["cell"] = cell;
        nb::dict fmt;
        fmt["name"] = c.name; fmt["hq"] = c.hq_city;
        fmt["kind"] = FAC_NAMES[kind];
        emit("facility", nb::cast(c.name), data, fmt);
        note_link(c, chain_stage(c));
        return true;
    };
    double raw_vals[4];
    for (int i = 0; i < 4; ++i) raw_vals[i] = c.stocks[RAW_ORD[i]];
    double raw_total = neumaier_sum_it(raw_vals, raw_vals + 4);
    if (has_kind(c, 0) && !has_kind(c, 1)
            && raw_total > pol_.refinery_raw_trigger
            && spendable > FAC_COST[1] * mult)
        return build(1);
    double mv_vals[3] = {c.stocks[5] * BASE_PRICES[5],
                         c.stocks[4] * BASE_PRICES[4],
                         c.stocks[6] * BASE_PRICES[6]};
    double metal_value = neumaier_sum_it(mv_vals, mv_vals + 3);
    double need = c.tr_vert > 0.7 ? pol_.factory_need_vertical
                                  : pol_.factory_need_default;
    if (has_kind(c, 1) && !has_kind(c, 2) && metal_value > need
            && spendable > FAC_COST[2] * mult)
        return build(2);
    if (has_kind(c, 2) && !has_kind(c, 3)
            && c.stocks[8] > pol_.plant_component_trigger
            && spendable > FAC_COST[3] * mult)
        return build(3);
    if (has_kind(c, 3) && !has_kind(c, 4)
            && c.stocks[9] > pol_.assembly_device_trigger
            && c.cash > FAC_COST[4] + pol_.assembly_cash_cushion)
        return build(4);
    return false;
}

void World::plan_buys(Company& c) {
    double spendable = c.cash - reserve(c);
    if (spendable <= 0) return;
    double scale = pol_.buy_target_scale;
    std::vector<std::pair<int, double>> wants;
    if (has_kind(c, 2)) {
        if (c.stocks[5] < 4.0) wants.emplace_back(5, 6.0 * scale);
        if (c.stocks[4] < 1.5) wants.emplace_back(4, 2.5 * scale);
    }
    if (has_kind(c, 3) && c.stocks[8] < 12) wants.emplace_back(8, 20.0 * scale);
    if (has_kind(c, 4) && c.stocks[9] < 10) wants.emplace_back(9, 12.0 * scale);
    double budget = spendable * pol_.buy_budget_frac;
    for (auto& w : wants) {
        double cost = w.second * prices_[w.first];
        if (cost <= budget) {
            c.buys[w.first] = w.second;
            budget -= cost;
        }
    }
}

double World::buffer(const Company& c, int comm) const {
    double v = (0.5 + c.tr_vert) * pol_.buffer_scale;
    bool is_raw = comm == 0 || comm == 1 || comm == 2 || comm == 3;
    if (is_raw && has_kind(c, 1)) return 220.0 * v;
    if ((comm == 5 || comm == 4) && has_kind(c, 2))
        return (comm == 5 ? 6.0 : 2.0) * v;
    if (comm == 8 && has_kind(c, 3)) return 30.0 * v;
    if (comm == 9 && has_kind(c, 4)) return 15.0 * v;
    return 0.0;
}

void World::plan_sells(Company& c) {
    for (int i = 0; i < NC; ++i) {
        double surplus = c.stocks[i] - buffer(c, i);
        if (surplus > 0.01) c.offers[i] = surplus;
    }
}

void World::use_tools(Company& c) {
    if (!has_kind(c, 3)) return;
    double res = reserve(c);
    if (!(tick_ <= c.insta_until)
            && rng.random() < c.tr_mkt * 0.45 * pol_.insta_prob_scale
            && c.cash - res > 9.0 * 400000 / 1000.0) {
        spend(c, 9.0 * 400000 / 1000.0, "tools");
        c.insta_until = tick_ + INSTA_DURATION;
        c.insta_strength = 1.0;
        nb::dict fmt; fmt["name"] = c.name; fmt["tool"] = "insta";
        emit("tool", nb::cast(c.name), nb::dict(), fmt);
    }
    if (!(tick_ <= c.zap_until) && c.stocks[9] > 20
            && rng.random() < c.tr_mkt * 0.35 * pol_.zap_prob_scale
            && c.cash - res > 0.05 * 60000) {
        spend(c, 0.05 * 60000, "tools");
        c.zap_until = tick_ + ZAP_DURATION;
        nb::dict fmt; fmt["name"] = c.name; fmt["tool"] = "zap";
        emit("tool", nb::cast(c.name), nb::dict(), fmt);
    }
    if (!(tick_ <= c.vid_until) && c.tr_mkt >= 0.6 && c.stocks[9] > 10
            && c.cash - res > 6000.0 * 4) {
        spend(c, 6000.0 * 4, "tools");
        c.vid_until = tick_ + VID_DURATION;
        nb::dict fmt; fmt["name"] = c.name; fmt["tool"] = "vid";
        emit("tool", nb::cast(c.name), nb::dict(), fmt);
    }
    if (!(tick_ <= c.loja_until) && c.stocks[9] >= 15
            && c.cash - res > 5000.0) {
        spend(c, 5000.0, "tools");
        c.loja_until = tick_ + LOJA_DURATION;
        nb::dict fmt; fmt["name"] = c.name; fmt["tool"] = "loja";
        emit("tool", nb::cast(c.name), nb::dict(), fmt);
    }
}

void World::decide(Company& c) {
    c.offers.fill(0.0);
    c.buys.fill(0.0);
    if (!c.alive) return;
    double spendable = c.cash - reserve(c);
    bool capex_done = false;
    if (equip_v2_) maintain_equipment(c);
    // 1) mineração
    int mine_count = 0;
    for (auto& f : c.facilities) if (f.kind == 0) ++mine_count;
    int desired_mines = 1 + int(c.tr_aggr * pol_.mines_coef);
    if (mine_count < desired_mines) {
        int target = pick_deposit(c);
        if (target >= 0) {
            const Deposit& dep = deposits_[size_t(target)];
            auto known = c.knowledge.find(dep.name);
            if (known == c.knowledge.end()) {
                if (spendable > PROBE_COST) {
                    spend(c, PROBE_COST, "probe");
                    c.knowledge[dep.name] = {dep.grade, dep.size_t};
                    if (dep.grade >= 0.78 || dep.grade <= 0.35) {
                        nb::dict fmt;
                        fmt["name"] = c.name; fmt["deposit"] = dep.name;
                        fmt["grade"] = dep.grade;
                        emit("probe", nb::cast(c.name), nb::dict(), fmt);
                    }
                }
            } else if (!capex_done) {
                double grade = known->second.first;
                double threshold = pol_.grade_thr_base
                                   - c.tr_risk * pol_.grade_thr_risk;
                std::string country = deposit_country(
                    deposits_[size_t(target)]);
                double mult = capex_mult(country);
                double cost = (CLAIM_COST + FAC_COST[0]) * mult;
                if (grade >= threshold && spendable > cost) {
                    auto cell = std::make_pair(dep.cell_r, dep.cell_c);
                    if (!c.claimed.count(cell)) {
                        spend(c, CLAIM_COST * mult, "claim");
                        c.claimed.insert(cell);
                        claimed_by_[cell] = c.cid;
                    }
                    spend(c, FAC_COST[0] * mult, "build");
                    c.fac_n += 1;
                    Facility f;
                    f.id = "f" + std::to_string(c.cid) + "-"
                           + std::to_string(c.fac_n);
                    f.kind = 0;
                    f.cell_r = dep.cell_r; f.cell_c = dep.cell_c;
                    f.deposit = target;
                    c.facilities.push_back(f);
                    c.kinds_mask |= 1u;
                    nb::dict data;
                    data["cid"] = c.cid; data["fid"] = f.id;
                    data["facility_kind"] = "mine";
                    nb::list cell_l; cell_l.append(f.cell_r);
                    cell_l.append(f.cell_c);
                    data["cell"] = cell_l;
                    data["deposit"] = dep.name;
                    nb::dict fmt;
                    fmt["name"] = c.name; fmt["deposit"] = dep.name;
                    emit("mine", nb::cast(c.name), data, fmt);
                    note_link(c, 1);
                    capex_done = true;
                }
            }
        }
    }
    // 2) jusante
    if (!capex_done) build_downstream(c, spendable);
    // 3) compras, 4) vendas, 5) ferramentas
    plan_buys(c);
    plan_sells(c);
    use_tools(c);
}

// ------------------------------------------------------------------ //
// Equipamentos (B2) — transcrição de engine.py/equipdata.py          //
// ------------------------------------------------------------------ //
void World::wear_and_roll(Company& c, Facility& f, double utilization) {
    EquipState& eq = f.equip;
    const auto& p = equip_.fac[f.kind];
    eq.cond = std::max(0.0, eq.cond - p.wear_rate * utilization
                                     * equip_.wear_scale);
    double base = (double(eq.age + 1) / p.eta);
    double prev = (double(eq.age) / p.eta);
    double hazard = 1.0 - std::exp(-(std::pow(base, p.beta)
                                     - std::pow(prev, p.beta)));
    double q = hazard * equip_.hazard_scale;
    if (q > 0.0 && rng.random() < q) break_facility(c, f);
}

void World::break_facility(Company& c, Facility& f) {
    EquipState& eq = f.equip;
    eq.broken = true;
    eq.repair_cost = FAC_COST[f.kind] * rng.uniform(equip_.repair_frac_min,
                                                    equip_.repair_frac_max);
    double raw = rng.lognormvariate(equip_.repair_mu, equip_.repair_sigma);
    int64_t rounded = int64_t(std::rint(raw));   // round() do Python
    eq.repair_ticks = std::max(equip_.repair_ticks_min,
                               std::min(equip_.repair_ticks_max, rounded));
    equip_stats_[size_t(c.cid)].breaks += 1;
    nb::dict data;
    data["cid"] = c.cid; data["fid"] = f.id;
    data["facility_kind"] = FAC_NAMES[f.kind];
    data["age"] = eq.age; data["condition"] = eq.cond;
    data["repair_cost"] = eq.repair_cost;
    data["repair_ticks"] = eq.repair_ticks;
    nb::dict fmt;
    fmt["name"] = c.name; fmt["kind"] = FAC_NAMES[f.kind];
    fmt["age"] = eq.age; fmt["cond"] = eq.cond;
    fmt["repair_cost"] = eq.repair_cost;
    fmt["repair_ticks"] = eq.repair_ticks;
    emit("breakdown", nb::cast(c.name), data, fmt);
}

void World::repair_facility(Company& c, Facility& f) {
    EquipState& eq = fac_equip(f);
    double cost = eq.repair_cost;
    spend(c, cost, "repair");
    eq.broken = false;
    eq.down_until = tick_ + eq.repair_ticks - 1;
    equip_stats_[size_t(c.cid)].repairs += 1;
    nb::dict data;
    data["cid"] = c.cid; data["fid"] = f.id;
    data["facility_kind"] = FAC_NAMES[f.kind];
    data["action"] = "repair"; data["cost"] = cost;
    data["repair_ticks"] = eq.repair_ticks;
    nb::dict fmt;
    fmt["name"] = c.name; fmt["kind"] = FAC_NAMES[f.kind];
    fmt["cost"] = cost; fmt["repair_ticks"] = eq.repair_ticks;
    emit("maintenance", nb::cast(c.name), data, fmt);
}

void World::maintain_facility(Company& c, Facility& f) {
    EquipState& eq = fac_equip(f);
    double cost = FAC_COST[f.kind] * equip_.maint_frac;
    spend(c, cost, "maintenance");
    double before = eq.cond;
    eq.cond = std::min(1.0, before + equip_.maint_restore);
    equip_stats_[size_t(c.cid)].maintenances += 1;
    if (before <= equip_.maint_downtime_h) {
        eq.down_until = std::max(eq.down_until, tick_);
        nb::dict data;
        data["cid"] = c.cid; data["fid"] = f.id;
        data["facility_kind"] = FAC_NAMES[f.kind];
        data["action"] = "preventive"; data["cost"] = cost;
        data["condition_before"] = before;
        data["condition_after"] = eq.cond;
        nb::dict fmt;
        fmt["name"] = c.name; fmt["kind"] = FAC_NAMES[f.kind];
        fmt["before"] = before; fmt["cost"] = cost;
        fmt["after"] = eq.cond;
        emit("maintenance", nb::cast(c.name), data, fmt);
    }
}

void World::overhaul_facility(Company& c, Facility& f) {
    EquipState& eq = fac_equip(f);
    double cost = FAC_COST[f.kind] * equip_.overhaul_frac;
    spend(c, cost, "overhaul");
    int64_t age_before = eq.age;
    eq.age = 0;
    eq.cond = 1.0;
    equip_stats_[size_t(c.cid)].overhauls += 1;
    nb::dict data;
    data["cid"] = c.cid; data["fid"] = f.id;
    data["facility_kind"] = FAC_NAMES[f.kind];
    data["action"] = "overhaul"; data["cost"] = cost;
    data["age_before"] = age_before;
    nb::dict fmt;
    fmt["name"] = c.name; fmt["kind"] = FAC_NAMES[f.kind];
    fmt["cost"] = cost; fmt["age_before"] = age_before;
    emit("maintenance", nb::cast(c.name), data, fmt);
}

// ------------------------------------------------------------------ //
// Produção — transcrição de Engine._produce                          //
// ------------------------------------------------------------------ //
void World::produce(Company& c) {
    if (!c.alive) return;
    for (auto& fac : c.facilities) {
        int kind = fac.kind;
        double cap = FAC_CAPACITY[kind];
        double cost = FAC_OPCOST[kind];
        bool has_eq = false;
        double thru = 0.0;
        if (equip_v2_) {
            EquipState& eq = fac_equip(fac);
            auto& st = equip_stats_[size_t(c.cid)];
            st.fac_ticks += 1;
            eq.age += 1;
            if (eq.broken || tick_ <= eq.down_until) {
                st.down_ticks += 1;
                continue;
            }
            double derate = equip_.age_derate * std::min(
                1.0, double(eq.age) / equip_.age_derate_months);
            cap = FAC_CAPACITY[kind] * eq.cond * (1.0 - derate);
            has_eq = true;
        }
        if (kind == 0) {
            const Deposit& dep = deposits_[size_t(fac.deposit)];
            std::string dcountry = deposit_country(dep);
            if (country_v2_ && is_halted(dcountry)) continue;
            double crude = std::min(cap, remaining_[size_t(fac.deposit)]);
            if (crude <= 0) continue;
            thru = crude;
            remaining_[size_t(fac.deposit)] -= crude;
            double payable = crude * dep.grade;
            double waste = crude - payable;
            c.stocks[dep.resource] += payable;
            ledger_[dep.resource].extracted += payable;
            ledger_[dep.resource].wasted += waste;
            ops_spend(c, dcountry, crude * cost);
        } else if (kind == 1) {
            double budget = cap;
            std::string hq_country = city_country(c.hq_city);
            for (int i = 0; i < 4; ++i) {
                if (budget <= 0) break;
                int raw = RAW_ORD[i], ref = REFINED_OF[i];
                double qty = std::min(c.stocks[raw], budget);
                if (qty <= 0) continue;
                budget -= qty;
                thru += qty;
                convert(c, raw, qty, ref, qty * REFINE_YIELD);
                ops_spend(c, hq_country, qty * cost);
            }
        } else {
            // factory/plant/assembly: receitas em unidades inteiras
            int product = kind == 2 ? 8 : (kind == 3 ? 9 : 10);
            // entradas na ordem do dict da receita
            int in_idx[3]; double in_per[3]; int n_in = 0;
            if (kind == 2) { in_idx[0]=5; in_per[0]=0.020; in_idx[1]=4; in_per[1]=0.005; n_in=2; }
            if (kind == 3) { in_idx[0]=8; in_per[0]=2.0; in_idx[1]=6; in_per[1]=0.050; in_idx[2]=7; in_per[2]=0.020; n_in=3; }
            if (kind == 4) { in_idx[0]=9; in_per[0]=10.0; in_idx[1]=8; in_per[1]=5.0; n_in=2; }
            double max_units = cap;
            for (int j = 0; j < n_in; ++j)
                max_units = std::min(max_units, c.stocks[in_idx[j]] / in_per[j]);
            int64_t units = int64_t(max_units);      // int() do Python
            if (units <= 0) continue;
            thru = double(units) * 1.0;
            for (int j = 0; j < n_in; ++j) {
                double qty = double(units) * in_per[j];
                c.stocks[in_idx[j]] -= qty;
                ledger_[in_idx[j]].consumed += qty;
            }
            c.stocks[product] += double(units) * 1.0;
            ledger_[product].produced += double(units) * 1.0;
            ops_spend(c, city_country(c.hq_city), double(units) * cost);
            if (product == 10) {
                total_super_ += double(units);
                bool found = false;
                for (auto& kv : super_by_cid_)
                    if (kv.first == c.cid) { kv.second += double(units); found = true; }
                if (!found) super_by_cid_.emplace_back(c.cid, double(units));
                emit("record_super", nb::cast(c.name), nb::dict(), nb::dict());
            }
        }
        if (has_eq && thru > 0.0) {
            double cap_now = cap;
            wear_and_roll(c, fac, cap_now > 0 ? thru / cap_now : 0.0);
        }
    }
    if (country_v2_) {
        auto it = royalty_due_.find(c.cid);
        double due = it == royalty_due_.end() ? 0.0 : it->second;
        if (it != royalty_due_.end()) royalty_due_.erase(it);
        if (due > 0.0) spend(c, due, "royalty");
    }
}

// ------------------------------------------------------------------ //
// Mercado vivo (B1): avanço mensal e recordes                        //
// ------------------------------------------------------------------ //
void World::narrate_regime(int comm, int new_regime) {
    nb::dict data;
    data["commodity"] = COMM_NAMES[comm];
    data["regime"] = new_regime == REG_BOOM ? "boom" : "bust";
    data["anchor"] = anchors_[comm];
    data["cover"] = cover_[comm];
    nb::dict fmt;
    fmt["commodity"] = COMM_NAMES[comm];
    fmt["regime"] = new_regime == REG_BOOM ? "boom" : "bust";
    fmt["anchor"] = anchors_[comm];
    fmt["cover"] = cover_[comm];
    emit("market_regime", nb::none(), data, fmt);
}

void World::advance_market() {
    for (int ci = 0; ci < NC; ++ci) {
        int comm = SORTED_IDX[ci];
        const MarketComm& p = mkt_.comm[comm];
        int regime = regime_[comm];
        regime_months_[comm] += 1;
        if (rng.random() < 1.0 / p.dur[regime]) {
            int nw;
            if (regime == REG_NORMAL)
                nw = rng.random() < 0.5 ? REG_BOOM : REG_BUST;
            else
                nw = REG_NORMAL;
            regime_[comm] = nw;
            regime_months_[comm] = 0;
            regime = nw;
            if (nw == REG_BOOM || nw == REG_BUST)
                narrate_regime(comm, nw);
        }
        if (regime == REG_BOOM)
            anchors_[comm] *= 1.0 + p.drift_boom;
        else if (regime == REG_BUST)
            anchors_[comm] *= 1.0 - p.drift_bust;
        else
            anchors_[comm] += (BASE_PRICES[comm] - anchors_[comm]) * 0.01;
        fair_noise_[comm] = rng.gauss(0.0, p.sigma_monthly);
    }
}

void World::note_price_record(int comm, double new_price,
                              const std::vector<double>& prev_ring) {
    double brk = mkt_.record_min_break;
    double rev = mkt_.record_reversal;
    int& dir = record_dir_[comm];
    double& extreme = record_extreme_[comm];
    if (dir == 1 && new_price < extreme * (1.0 - rev)) dir = 0;
    else if (dir == -1 && new_price > extreme * (1.0 + rev)) dir = 0;
    double mx = prev_ring[0], mn = prev_ring[0];
    for (double v : prev_ring) { mx = std::max(mx, v); mn = std::min(mn, v); }
    int64_t window = int64_t(prev_ring.size()) + 1;
    if (new_price > mx * (1.0 + brk)) {
        if (dir == 1) { extreme = std::max(extreme, new_price); return; }
        dir = 1; extreme = new_price;
        nb::dict data;
        data["commodity"] = COMM_NAMES[comm]; data["price"] = new_price;
        data["direction"] = "high"; data["window"] = window;
        nb::dict fmt;
        fmt["commodity"] = COMM_NAMES[comm]; fmt["price"] = new_price;
        fmt["direction"] = "high"; fmt["window"] = window;
        emit("price_record", nb::none(), data, fmt);
    } else if (new_price < mn * (1.0 - brk)) {
        if (dir == -1) { extreme = std::min(extreme, new_price); return; }
        dir = -1; extreme = new_price;
        nb::dict data;
        data["commodity"] = COMM_NAMES[comm]; data["price"] = new_price;
        data["direction"] = "low"; data["window"] = window;
        nb::dict fmt;
        fmt["commodity"] = COMM_NAMES[comm]; fmt["price"] = new_price;
        fmt["direction"] = "low"; fmt["window"] = window;
        emit("price_record", nb::none(), data, fmt);
    } else if (dir == 1) {
        extreme = std::max(extreme, new_price);
    } else if (dir == -1) {
        extreme = std::min(extreme, new_price);
    }
}

// ------------------------------------------------------------------ //
// Comércio (compartilhado clássico/vivo)                             //
// ------------------------------------------------------------------ //
void World::trade_internal(
        int comm, double price,
        const std::vector<std::pair<int, double>>& offers,
        const std::vector<std::pair<int, double>>& buys,
        std::map<int, double>& offered_left,
        std::optional<std::map<int, double>>& received) {
    for (auto& bw : buys) {           // buys já vem em ordem de cid
        double want = bw.second;
        if (want <= 0) continue;
        Company& buyer = companies_[size_t(bw.first)];
        std::vector<double> left_vals;
        for (auto& o : offers) left_vals.push_back(offered_left[o.first]);
        double total_left = neumaier_sum_it(left_vals.begin(),
                                            left_vals.end());
        if (total_left <= 0) break;
        double fill = std::min(want, total_left);
        for (auto& o : offers) {
            int sid = o.first;
            if (sid == bw.first) continue;
            double left = offered_left[sid];
            if (left <= 0) continue;
            double share = fill * (left / total_left);
            double cash_cap = price > 0 ? buyer.cash / price : 0.0;
            share = std::min({share, left, cash_cap});
            if (share <= 0.0001) continue;
            Company& seller = companies_[size_t(sid)];
            seller.stocks[comm] -= share;
            buyer.stocks[comm] += share;
            seller.cash += share * price;
            buyer.cash -= share * price;
            flow(sid, "trade_in", share * price);
            flow(bw.first, "trade_out", -share * price);
            offered_left[sid] -= share;
            if (received.has_value())
                (*received)[bw.first] = ((*received).count(bw.first)
                    ? (*received)[bw.first] : 0.0) + share;
        }
    }
}

double World::city_sales(
        int comm, double price, double city_q,
        const std::vector<std::pair<int, double>>& offers,
        std::map<int, double>& offered_left) {
    double city_sold = 0.0;
    std::vector<double> left_vals;
    for (auto& o : offers) left_vals.push_back(offered_left[o.first]);
    double left_total = neumaier_sum_it(left_vals.begin(), left_vals.end());
    if (!(city_q > 0 && left_total > 0)) return 0.0;
    std::map<int, double> weights;
    std::vector<double> w_vals;
    for (auto& o : offers) {
        Company& seller = companies_[size_t(o.first)];
        double w = offered_left[o.first];
        if (tick_ <= seller.insta_until && comm == 9) w *= 2.2;
        if (tick_ <= seller.vid_until && (comm == 9 || comm == 10))
            w *= VID_DEMAND_WEIGHT;
        if (tick_ <= seller.zap_until) w *= 1.3;
        if (tick_ <= seller.loja_until && comm == 9) w *= LOJA_DEMAND_WEIGHT;
        weights[o.first] = w;
        w_vals.push_back(w);
    }
    double wsum = neumaier_sum_it(w_vals.begin(), w_vals.end());
    for (auto& o : offers) {
        if (wsum <= 0) break;
        Company& seller = companies_[size_t(o.first)];
        double qty = std::min(offered_left[o.first],
                              city_q * weights[o.first] / wsum);
        if (qty <= 0.0001) continue;
        seller.stocks[comm] -= qty;
        seller.cash += qty * price;
        flow(o.first, "city_sales", qty * price);
        money_in_ += qty * price;
        ledger_[comm].sold_external += qty;
        offered_left[o.first] -= qty;
        city_sold += qty;
        if (comm == 9 && tick_ <= seller.loja_until) {
            double fee = qty * price * LOJA_FEE_PCT;
            seller.cash -= fee;
            money_out_ += fee;
            flow(o.first, "spend_tools", -fee);
        }
    }
    return city_sold;
}

std::pair<double, double> World::parity(int comm) const {
    double anchor = anchors_[comm];
    double mult = 1.0;
    auto it = parity_surcharge_.find(comm);
    if (it != parity_surcharge_.end()) mult = it->second;
    return {anchor * (1.0 + ctry_.tariff + ctry_.freight) * mult,
            anchor * (1.0 - ctry_.freight) * mult};
}

std::pair<double, double> World::external_trade(
        int comm, const std::vector<std::pair<int, double>>& offers,
        std::map<int, double>& offered_left,
        const std::optional<std::vector<std::pair<int, double>>>&
            unfilled_buyers,
        double price, double city_unfilled) {
    auto [p_imp, p_exp] = parity(comm);
    double cap = std::max(CITY_DEMAND[comm], ctry_.ore_scale)
                 * ctry_.capacity_factor;
    double cap_max = cap * ctry_.max_spread_mult;
    double imported = 0.0, exported = 0.0;
    bool has_unfilled = unfilled_buyers.has_value()
                        && !unfilled_buyers->empty();
    if (price > p_imp && (has_unfilled || city_unfilled > 0.0001)) {
        double budget = std::min(cap * (price / p_imp - 1.0), cap_max);
        if (unfilled_buyers.has_value()) {
            for (auto& uw : *unfilled_buyers) {
                if (budget <= 0) break;
                Company& comp = companies_[size_t(uw.first)];
                double cash_cap = price > 0 ? comp.cash / price : 0.0;
                double qty = std::min({uw.second, budget, cash_cap});
                if (qty <= 0.0001) continue;
                comp.stocks[comm] += qty;
                comp.cash -= qty * price;
                flow(uw.first, "import_buy", -qty * price);
                money_to_external_ += qty * price;
                ledger_[comm].imported += qty;
                imported += qty;
                budget -= qty;
            }
        }
        if (budget > 0 && city_unfilled > 0.0001) {
            double qty = std::min(city_unfilled, budget);
            ledger_[comm].imported += qty;
            ledger_[comm].sold_external += qty;
            imported += qty;
            budget -= qty;
        }
    }
    if (price < p_exp && !offers.empty()) {
        double budget = std::min(cap * (1.0 - price / p_exp), cap_max);
        for (auto& o : offers) {
            if (budget <= 0) break;
            double left = offered_left[o.first];
            if (left <= 0.0001) continue;
            double qty = std::min(left, budget);
            Company& seller = companies_[size_t(o.first)];
            seller.stocks[comm] -= qty;
            seller.cash += qty * price;
            flow(o.first, "export_sale", qty * price);
            money_from_external_ += qty * price;
            ledger_[comm].sold_external += qty;
            offered_left[o.first] -= qty;
            exported += qty;
            budget -= qty;
        }
    }
    return {imported, exported};
}

// ------------------------------------------------------------------ //
// O mercado por commodity                                            //
// ------------------------------------------------------------------ //
void World::market_classic(int comm) {
    double price = prices_[comm];
    std::vector<std::pair<int, double>> offers, buys;
    for (auto& c : companies_) {
        if (!c.alive) continue;
        double q = c.offers[comm];
        if (q > 0.001) offers.emplace_back(c.cid, q);
        buys.emplace_back(c.cid, c.buys[comm]);
    }
    std::vector<double> offer_vals, buy_vals;
    for (auto& o : offers) offer_vals.push_back(o.second);
    for (auto& b : buys) buy_vals.push_back(b.second);
    double total_supply = neumaier_sum_it(offer_vals.begin(),
                                          offer_vals.end());
    if (total_supply <= 0 && !country_v2_) return;
    double internal_demand = neumaier_sum_it(buy_vals.begin(),
                                              buy_vals.end());
    std::map<int, double> offered_left;
    for (auto& o : offers) offered_left[o.first] = o.second;
    std::optional<std::map<int, double>> received;
    if (country_v2_ && price > parity(comm).first)
        received = std::map<int, double>{};
    trade_internal(comm, price, offers, buys, offered_left, received);
    double city_q = CITY_DEMAND[comm] * demand_factor(comm);
    double city_sold = city_sales(comm, price, city_q, offers, offered_left);
    double demand_extra = 0.0, supply_extra = 0.0;
    if (country_v2_) {
        std::optional<std::vector<std::pair<int, double>>> unfilled;
        if (received.has_value()) {
            std::vector<std::pair<int, double>> u;
            for (auto& b : buys) {
                double got = received->count(b.first)
                             ? (*received)[b.first] : 0.0;
                if (b.second - got > 0.0001)
                    u.emplace_back(b.first, b.second - got);
            }
            unfilled = u;
        }
        auto [imported, exported] = external_trade(
            comm, offers, offered_left, unfilled, price,
            city_q - city_sold);
        demand_extra = exported;
        supply_extra = imported;
    }
    double demand = internal_demand + city_q + demand_extra;
    total_supply += supply_extra;
    double ratio = (demand - total_supply)
                   / std::max({demand, total_supply, 1.0});
    double factor = std::min(1.35, std::max(0.72, 1.0 + 0.10 * ratio));
    double base = BASE_PRICES[comm];
    prices_[comm] = std::min(base * 3.0,
                             std::max(base * 0.3, price * factor));
}

void World::market_living(int comm) {
    const MarketComm& p = mkt_.comm[comm];
    double price = prices_[comm];
    double anchor = anchors_[comm];
    std::vector<std::pair<int, double>> offers, buys;
    for (auto& c : companies_) {
        if (!c.alive) continue;
        double q = c.offers[comm];
        if (q > 0.001) offers.emplace_back(c.cid, q);
        buys.emplace_back(c.cid, c.buys[comm]);
    }
    std::vector<double> offer_vals, buy_vals;
    for (auto& o : offers) offer_vals.push_back(o.second);
    for (auto& b : buys) buy_vals.push_back(b.second);
    double total_supply = neumaier_sum_it(offer_vals.begin(),
                                          offer_vals.end());
    double internal_demand = neumaier_sum_it(buy_vals.begin(),
                                              buy_vals.end());
    double total_stocks = tick_stock_totals_[size_t(comm)];
    double cover = total_stocks / std::max(demand_ema_[comm], 1.0);
    cover_[comm] = cover;
    double fair = anchor * std::exp(-p.gamma * (cover - p.cover_target))
                  * std::exp(fair_noise_[comm]);
    double d0 = CITY_DEMAND[comm];
    double city_q = 0.0;
    if (d0 > 0) {
        double seasonal = tick_seasonal_[size_t(comm)];
        city_q = d0 * std::pow(price / anchor, -p.elasticity) * seasonal
                 * demand_factor(comm);
    }
    std::map<int, double> offered_left;
    for (auto& o : offers) offered_left[o.first] = o.second;
    std::optional<std::map<int, double>> received;
    if (country_v2_ && price > parity(comm).first)
        received = std::map<int, double>{};
    double city_sold = 0.0;
    if (total_supply > 0) {
        trade_internal(comm, price, offers, buys, offered_left, received);
        city_sold = city_sales(comm, price, city_q, offers, offered_left);
    }
    double imported = 0.0, exported = 0.0;
    if (country_v2_) {
        std::optional<std::vector<std::pair<int, double>>> unfilled;
        if (received.has_value()) {
            std::vector<std::pair<int, double>> u;
            for (auto& b : buys) {
                double got = received->count(b.first)
                             ? (*received)[b.first] : 0.0;
                if (b.second - got > 0.0001)
                    u.emplace_back(b.first, b.second - got);
            }
            unfilled = u;
        }
        auto pr = external_trade(comm, offers, offered_left, unfilled,
                                  price, city_q - city_sold);
        imported = pr.first;
        exported = pr.second;
    }
    double demand_total = internal_demand + city_q;
    double alpha = mkt_.ema_alpha;
    double ema = demand_ema_[comm];
    demand_ema_[comm] = ema + alpha * (demand_total - ema);
    double ratio_demand = demand_total + exported;
    double ratio_supply = total_supply + imported;
    double ratio = (ratio_demand - ratio_supply)
                   / std::max({ratio_demand, ratio_supply, 1.0});
    double factor = std::min(1.6, std::max(0.6, 1.0 + 0.10 * ratio));
    double new_price = price * factor;
    new_price += p.kappa * (fair - new_price);
    new_price = std::min(mkt_.band_hi * anchor,
                         std::max(mkt_.band_lo * anchor, new_price));
    prices_[comm] = new_price;
    auto& ring = price_ring_[comm];
    ring.push_back(new_price);
    int64_t window = mkt_.record_window;
    if (int64_t(ring.size()) > window)
        ring.erase(ring.begin(), ring.end() - window);
    if (ring.size() >= 12) {
        std::vector<double> prev(ring.begin(), ring.end() - 1);
        note_price_record(comm, new_price, prev);
    }
}

void World::market() {
    if (market_v2_) {
        tick_stock_totals_.fill(0.0);
        for (auto& c : companies_)
            for (int i = 0; i < NC; ++i)
                tick_stock_totals_[size_t(i)] += c.stocks[i];
        for (int ci = 0; ci < NC; ++ci) {
            int comm = SORTED_IDX[ci];
            const MarketComm& p = mkt_.comm[comm];
            tick_seasonal_[size_t(comm)] =
                1.0 + p.seasonal_amp * std::sin(
                    2.0 * M_PI * (double(tick_) + p.seasonal_phase) / 12.0);
        }
    }
    for (int ci = 0; ci < NC; ++ci) {
        int comm = SORTED_IDX[ci];
        if (market_v2_) market_living(comm);
        else market_classic(comm);
    }
}

// ------------------------------------------------------------------ //
// País e política (B3)                                               //
// ------------------------------------------------------------------ //
static double monthly_prob(double p_year) {
    return 1.0 - std::pow(1.0 - p_year, 1.0 / 12.0);
}

std::optional<std::string> World::hottest_resource(
        const std::string& country) {
    auto& res = country_resources(country);
    if (res.empty()) return std::nullopt;
    int best = res[0];
    double best_ratio = anchors_[best] != 0.0
                        ? prices_[best] / anchors_[best] : 0.0;
    for (size_t i = 1; i < res.size(); ++i) {
        int r = res[i];
        double ratio = anchors_[r] != 0.0 ? prices_[r] / anchors_[r] : 0.0;
        // max por (ratio, nome): desempate pelo maior nome
        if (ratio > best_ratio
                || (ratio == best_ratio
                    && std::string(COMM_NAMES[r]) > COMM_NAMES[best])) {
            best = r;
            best_ratio = ratio;
        }
    }
    return std::string(COMM_NAMES[best]);
}

bool World::reform_hot(const std::string& country) {
    double ratio = ctry_.model.reform_hot_ratio;
    for (int r : country_resources(country))
        if (prices_[r] > ratio * anchors_[r]) return true;
    return false;
}

void World::apply_political_event(
        const std::string& country, const std::string& event,
        const std::optional<std::string>& resource) {
    auto it = country_idx_.find(country);
    if (it == country_idx_.end())
        throw nb::value_error("evento político fora do mundo");
    Country& st = countries_[it->second];
    const CountryModel& m = ctry_.model;
    std::optional<std::string> res_text;
    nb::dict fmt;
    fmt["country"] = country;
    fmt["event"] = event;
    if (event == "royalty_reform") {
        st.tau = std::min(m.tau_max, st.tau + m.reform_tau_step);
        res_text = resource.has_value() ? resource
                                        : hottest_resource(country);
    } else if (event == "export_restriction") {
        const auto& res_list = country_resources(country);
        std::string res = resource.has_value()
            ? *resource
            : COMM_NAMES[res_list[size_t(
                  rng.choice_index(int64_t(res_list.size())))]];
        int64_t months = m.restriction_months;
        st.restrictions[res] = tick_ + months - 1;
        res_text = res;
        fmt["refined"] = COMM_NAMES[REFINED_OF_RAW[comm_index(res)]];
        fmt["months"] = months;
    } else if (event == "state_jv") {
        st.S_mean = std::max(m.smean_min, st.S_mean - m.jv_smean_drop);
        st.tau = std::min(m.tau_max, st.tau + m.jv_tau_step);
        if (resource.has_value()) res_text = resource;
        else {
            auto& res = country_resources(country);
            if (!res.empty()) res_text = COMM_NAMES[res[0]];
        }
    } else if (event == "judicial_halt") {
        int64_t months = m.halt_months_judicial;
        st.halt_until = std::max(st.halt_until, tick_ + months - 1);
        fmt["months"] = months;
    } else if (event == "subsidy") {
        st.tau = std::max(m.tau_min, st.tau + m.subsidy_tau_step);
    } else if (event == "disaster") {
        int64_t months = m.halt_months_disaster;
        st.halt_until = std::max(st.halt_until, tick_ + months - 1);
        st.S = std::max(m.s_min, st.S - m.disaster_s_shock);
        fmt["months"] = months;
    } else if (event == "election") {
        double shift = rng.uniform(-m.election_smean_shift,
                                   m.election_smean_shift);
        st.S_mean = std::min(m.smean_max,
                             std::max(m.smean_min, st.S_mean + shift));
        double step = m.election_tau_steps[size_t(
            rng.randbelow(int64_t(m.election_tau_steps.size())))];
        st.tau = std::min(m.tau_max, std::max(m.tau_min, st.tau + step));
    } else {
        throw nb::value_error("evento político desconhecido");
    }
    if (event == "subsidy")
        st.S_mean = std::min(m.smean_max,
                             st.S_mean + m.subsidy_smean_gain);
    nb::dict data;
    data["event"] = event;
    data["country"] = country;
    if (res_text.has_value()) data["commodity"] = *res_text;
    else data["commodity"] = nb::none();
    data["tau"] = st.tau;
    data["S"] = st.S;
    data["S_mean"] = st.S_mean;
    fmt["tau"] = st.tau;
    fmt["S"] = st.S;
    fmt["S_mean"] = st.S_mean;
    if (res_text.has_value()) fmt["resource"] = *res_text;
    emit("politics", nb::none(), data, fmt);
}

void World::advance_politics() {
    const CountryModel& m = ctry_.model;
    capex_memo_.clear();
    for (const auto& fe : force_events_) {
        if (fe.tick != tick_) continue;
        std::optional<std::string> res;
        if (fe.has_resource) res = fe.resource;
        apply_political_event(fe.country, fe.event, res);
    }
    int64_t period = m.election_period;
    for (auto& st : countries_) {
        const std::string& name = st.name;
        st.S = std::min(m.s_max, std::max(m.s_min,
                        st.S + m.s_reversion * (st.S_mean - st.S)
                        + rng.gauss(0.0, m.s_sigma)));
        double target = 1.0 + m.fx_beta * (st.S_mean - st.S);
        st.fx = std::min(m.fx_max, std::max(m.fx_min,
                         st.fx + m.fx_reversion * (target - st.fx)
                         + rng.gauss(0.0, m.fx_sigma)));
        if (tick_ > 0
                && (tick_ - election_offset_[name]) % period == 0)
            apply_political_event(name, "election", std::nullopt);
        double p_reform = monthly_prob(ctry_.ev_reform);
        if (reform_hot(name)) p_reform = std::min(1.0, 2.0 * p_reform);
        if (rng.random() < p_reform)
            apply_political_event(name, "royalty_reform", std::nullopt);
        if (!country_resources(name).empty()) {
            if (rng.random() < monthly_prob(ctry_.ev_restriction))
                apply_political_event(name, "export_restriction",
                                      std::nullopt);
            if (rng.random() < monthly_prob(ctry_.ev_jv))
                apply_political_event(name, "state_jv", std::nullopt);
            if (rng.random() < monthly_prob(ctry_.ev_halt))
                apply_political_event(name, "judicial_halt", std::nullopt);
        }
        if (rng.random() < monthly_prob(ctry_.ev_subsidy))
            apply_political_event(name, "subsidy", std::nullopt);
        if (rng.random() < monthly_prob(ctry_.ev_disaster))
            apply_political_event(name, "disaster", std::nullopt);
    }
    parity_surcharge_.clear();
    double mult = 1.0 + m.restriction_parity_surcharge;
    for (auto& st : countries_) {
        for (auto& kv : st.restrictions) {
            if (tick_ <= kv.second) {
                int res = comm_index(kv.first);
                int ref = REFINED_OF_RAW[res];
                for (int c : {res, ref}) {
                    if (c < 0) continue;
                    auto cur = parity_surcharge_.find(c);
                    double base = cur == parity_surcharge_.end()
                                  ? 1.0 : cur->second;
                    parity_surcharge_[c] = std::max(base, mult);
                }
            }
        }
    }
}

// ------------------------------------------------------------------ //
// Falência / aquisição e rivalidade                                  //
// ------------------------------------------------------------------ //
std::string World::bankruptcy_cause(const Company& c) const {
    auto bit = c.spend_hist.find("build");
    if (bit != c.spend_hist.end() && tick_ - bit->second.second <= 6
            && bit->second.first >= 2000000.0)
        return "capex";
    auto ait = c.spend_hist.find("acquisition");
    if (ait != c.spend_hist.end() && tick_ - ait->second.second <= 6)
        return "aquisicao";
    if (equip_v2_ && !c.facilities.empty()) {
        for (auto& f : c.facilities)
            if (f.equip.present && f.equip.broken) return "quebra";
    }
    if (c.facilities.empty()) return "sem_operacao";
    std::vector<double> vals;
    for (int i = 0; i < NC; ++i) vals.push_back(c.stocks[i] * BASE_PRICES[i]);
    double stock_value = neumaier_sum_it(vals.begin(), vals.end());
    if (stock_value < 50000.0) return "operacao";
    return "caixa";
}

void World::check_bankruptcy(Company& c) {
    if (!c.alive || c.cash >= 0) return;
    c.alive = false;
    std::string cause = bankruptcy_cause(c);
    bankruptcies_count_ += 1;
    nb::dict data;
    data["cid"] = c.cid; data["cause"] = cause; data["cash"] = c.cash;
    nb::dict fmt;
    fmt["name"] = c.name; fmt["cash"] = c.cash; fmt["cause"] = cause;
    emit("bankruptcy", nb::cast(c.name), data, fmt);
    std::vector<int> buyers;
    for (auto& o : companies_)
        if (o.alive && o.cash > 12000000.0) buyers.push_back(o.cid);
    if (buyers.empty() || c.facilities.empty()) return;
    int buyer_id = buyers[0];
    for (int bid : buyers)
        if (companies_[size_t(bid)].cash
                > companies_[size_t(buyer_id)].cash)
            buyer_id = bid;
    Company& buyer = companies_[size_t(buyer_id)];
    std::vector<double> costs;
    for (auto& f : c.facilities) costs.push_back(FAC_COST[f.kind]);
    double price = neumaier_sum_it(costs.begin(), costs.end()) * 0.15;
    if (!(buyer.cash > price)) return;
    std::vector<std::string> facility_ids;
    for (auto& f : c.facilities) facility_ids.push_back(f.id);
    std::sort(facility_ids.begin(), facility_ids.end());
    spend(buyer, price, "acquisition");
    for (auto& fac : c.facilities) buyer.facilities.push_back(fac);
    for (auto cell : c.claimed) {
        buyer.claimed.insert(cell);
        claimed_by_[cell] = buyer.cid;
    }
    for (int i = 0; i < NC; ++i) {
        buyer.stocks[i] += c.stocks[i];
        c.stocks[i] = 0.0;
    }
    c.facilities.clear();
    buyer.kinds_mask = 0;
    for (auto& f : buyer.facilities) buyer.kinds_mask |= (1u << f.kind);
    c.kinds_mask = 0;
    nb::dict data2;
    data2["buyer_cid"] = buyer.cid; data2["from_cid"] = c.cid;
    nb::list ids;
    for (auto& s : facility_ids) ids.append(s);
    data2["facility_ids"] = ids;
    data2["price"] = price;
    nb::dict fmt2;
    fmt2["buyer"] = buyer.name; fmt2["dead"] = c.name;
    fmt2["price"] = price;
    emit("acquisition", nb::cast(buyer.name), data2, fmt2);
}

int World::leader(bool by_stage) const {
    int best = -1;
    double best_val = 0;
    for (auto& c : companies_) {
        if (!c.alive) continue;
        double v = by_stage ? double(chain_stage(c)) : c.cash;
        if (best < 0 || v > best_val) { best = c.cid; best_val = v; }
    }
    return best;
}

void World::note_rivalry() {
    int cl = leader(false);
    if (cl >= 0) {
        if (!cash_leader_.has_value()) {
            cash_leader_ = cl;
        } else if (cl != *cash_leader_) {
            const Company& old = companies_[size_t(*cash_leader_)];
            const Company& nw = companies_[size_t(cl)];
            nb::dict data;
            data["metric"] = "cash";
            data["from_cid"] = old.cid; data["to_cid"] = nw.cid;
            nb::dict fmt;
            fmt["new"] = nw.name; fmt["old"] = old.name;
            fmt["new_cash"] = nw.cash; fmt["old_cash"] = old.cash;
            fmt["metric"] = "cash";
            emit("rivalry", nb::cast(nw.name), data, fmt);
            cash_leader_ = cl;
        }
    }
    int sl = leader(true);
    if (sl >= 0 && chain_stage(companies_[size_t(sl)]) > 0) {
        if (!stage_leader_.has_value()) {
            stage_leader_ = sl;
        } else if (sl != *stage_leader_) {
            const Company& old = companies_[size_t(*stage_leader_)];
            const Company& nw = companies_[size_t(sl)];
            nb::dict data;
            data["metric"] = "stage";
            data["from_cid"] = old.cid; data["to_cid"] = nw.cid;
            nb::dict fmt;
            fmt["new"] = nw.name; fmt["old"] = old.name;
            fmt["new_stage"] = chain_stage(nw);
            fmt["old_stage"] = chain_stage(old);
            fmt["metric"] = "stage";
            emit("rivalry", nb::cast(nw.name), data, fmt);
            stage_leader_ = sl;
        }
    }
}

void World::emit_flows() {
    nb::dict companies;
    for (auto& c : companies_) {
        nb::dict flows;
        for (auto& kv : flows_[size_t(c.cid)])
            if (kv.second != 0.0) flows[pystr(kv.first)] = kv.second;
        nb::dict entry;
        entry["delta"] = c.cash - cash_start_[size_t(c.cid)];
        entry["cash"] = c.cash;
        entry["flows"] = flows;
        companies[pystr(std::to_string(c.cid))] = entry;
    }
    nb::dict data;
    data["companies"] = companies;
    emit("flows", nb::none(), data, nb::dict());
}

// ------------------------------------------------------------------ //
// O passo                                                            //
// ------------------------------------------------------------------ //
nb::list World::step() {
    nb::list events;
    ev_ = &events;
    cash_start_.clear();
    for (auto& c : companies_) cash_start_.push_back(c.cash);
    flows_.assign(companies_.size(), {});
    apply_god_events();
    if (country_v2_) advance_politics();
    if (market_v2_) advance_market();
    for (auto& c : companies_) {
        check_bankruptcy(c);
        decide(c);
    }
    for (auto& c : companies_) produce(c);
    market();
    note_rivalry();
    emit_flows();
    tick_ += 1;
    if (tick_ % 60 == 0) {
        // RESUMO DE ERA (a contagem de falências vem do contador do
        // motor, idêntico ao da crônica — ele emite cada falência)
        int64_t years = tick_ / 12;
        int richest = -1, top = -1, most_fac = -1;
        double rv = 0, tv = 0, fv = 0;
        int alive_n = 0;
        for (auto& c : companies_) {
            if (c.alive) alive_n += 1;
            if (richest < 0 || c.cash > rv) { richest = c.cid; rv = c.cash; }
            int st = chain_stage(c);
            if (top < 0 || st > tv) { top = c.cid; tv = st; }
            if (most_fac < 0 || int(c.facilities.size()) > fv) {
                most_fac = c.cid;
                fv = int(c.facilities.size());
            }
        }
        std::optional<int> top_producer;
        if (!super_by_cid_.empty()) {
            int bp = super_by_cid_[0].first;
            double bv = super_by_cid_[0].second;
            for (auto& kv : super_by_cid_)
                if (kv.second > bv
                        || (kv.second == bv && kv.first < bp)) {
                    bp = kv.first; bv = kv.second;
                }
            top_producer = bp;
        }
        nb::dict data;
        data["years"] = years;
        data["cash_leader"] = companies_[size_t(richest)].name;
        data["stage_leader"] = companies_[size_t(top)].name;
        data["supercomputers"] = int64_t(total_super_);
        if (top_producer.has_value())
            data["top_producer"] =
                companies_[size_t(*top_producer)].name;
        else
            data["top_producer"] = nb::none();
        data["bankruptcies"] = bankruptcies_count_;
        data["alive"] = alive_n;
        nb::dict fmt;
        fmt["years"] = years;
        fmt["richest"] = companies_[size_t(richest)].name;
        fmt["richest_cash"] = companies_[size_t(richest)].cash;
        fmt["top"] = companies_[size_t(top)].name;
        fmt["top_stage"] = chain_stage(companies_[size_t(top)]);
        fmt["most_fac"] = companies_[size_t(most_fac)].name;
        fmt["most_fac_n"] = int64_t(
            companies_[size_t(most_fac)].facilities.size());
        fmt["super_int"] = int64_t(total_super_);
        if (top_producer.has_value())
            fmt["top_producer"] =
                companies_[size_t(*top_producer)].name;
        fmt["bankruptcies"] = bankruptcies_count_;
        fmt["alive"] = alive_n;
        fmt["total"] = int64_t(companies_.size());
        emit("era_summary", nb::none(), data, fmt);
    }
    ev_ = nullptr;
    return events;
}

// ------------------------------------------------------------------ //
// Exportação de estado (a camada Python arredonda/formata)           //
// ------------------------------------------------------------------ //
nb::dict World::frame_data() const {
    nb::dict out;
    out["tick"] = tick_;
    nb::dict prices;
    for (int i = 0; i < NC; ++i) prices[COMM_NAMES[i]] = prices_[i];
    out["prices"] = prices;
    nb::list comps;
    for (auto& c : companies_) {
        nb::dict cd;
        cd["id"] = c.cid; cd["name"] = c.name;
        cd["archetype"] = c.archetype; cd["color"] = c.color;
        cd["hq"] = c.hq_city; cd["alive"] = c.alive;
        cd["cash"] = c.cash; cd["stage"] = chain_stage(c);
        nb::list terr;
        for (auto cell : c.claimed) {
            nb::list cl; cl.append(cell.first); cl.append(cell.second);
            terr.append(cl);
        }
        cd["territory"] = terr;
        nb::list facs;
        for (auto& f : c.facilities) {
            nb::dict fd;
            fd["kind"] = FAC_NAMES[f.kind];
            nb::list cl; cl.append(f.cell_r); cl.append(f.cell_c);
            fd["cell"] = cl;
            if (f.deposit >= 0)
                fd["deposit"] = deposits_[size_t(f.deposit)].name;
            else
                fd["deposit"] = nb::none();
            if (equip_v2_) {
                nb::dict eq;
                eq["age"] = f.equip.present ? f.equip.age : 0;
                eq["cond"] = f.equip.present ? f.equip.cond : 1.0;
                eq["down"] = f.equip.present
                    && (f.equip.broken || tick_ <= f.equip.down_until);
                fd["equip"] = eq;
            }
            facs.append(fd);
        }
        cd["facilities"] = facs;
        nb::dict stocks;
        for (int i = 0; i < NC; ++i) stocks[COMM_NAMES[i]] = c.stocks[i];
        cd["stocks"] = stocks;
        comps.append(cd);
    }
    out["companies"] = comps;
    nb::list deps;
    for (size_t i = 0; i < deposits_.size(); ++i) {
        nb::dict dd;
        dd["name"] = deposits_[i].name;
        dd["resource"] = COMM_NAMES[deposits_[i].resource];
        nb::list cl; cl.append(deposits_[i].cell_r);
        cl.append(deposits_[i].cell_c);
        dd["cell"] = cl;
        dd["lat"] = deposits_[i].lat; dd["lon"] = deposits_[i].lon;
        dd["remaining"] = remaining_[i];
        dd["size_t"] = deposits_[i].size_t;
        deps.append(dd);
    }
    out["deposits"] = deps;
    if (market_v2_) {
        nb::dict mkt;
        for (int i = 0; i < NC; ++i) {
            nb::dict e;
            e["anchor"] = anchors_[i];
            e["regime"] = regime_[i] == REG_BOOM ? "boom"
                          : regime_[i] == REG_BUST ? "bust" : "normal";
            e["cover"] = cover_[i];
            mkt[COMM_NAMES[i]] = e;
        }
        out["market"] = mkt;
    }
    if (country_v2_) {
        nb::dict pol;
        for (auto& st : countries_) {
            nb::dict e;
            e["S"] = st.S; e["fx"] = st.fx; e["tau"] = st.tau;
            pol[pystr(st.name)] = e;
        }
        out["politics"] = pol;
        nb::dict tr;
        for (int i = 0; i < NC; ++i) {
            auto pr = parity(i);
            nb::dict e;
            e["parity_import"] = pr.first;
            e["parity_export"] = pr.second;
            tr[COMM_NAMES[i]] = e;
        }
        out["trade"] = tr;
    }
    return out;
}

nb::dict World::result_data() const {
    nb::dict out;
    out["tick"] = tick_;
    out["seed"] = seed_;
    out["total_super"] = total_super_;
    nb::list comps;
    for (auto& c : companies_) {
        nb::dict cd;
        cd["name"] = c.name; cd["archetype"] = c.archetype;
        cd["alive"] = c.alive; cd["cash"] = c.cash;
        cd["stage"] = chain_stage(c);
        cd["facilities"] = int64_t(c.facilities.size());
        comps.append(cd);
    }
    out["companies"] = comps;
    if (market_v2_) {
        nb::dict mkt;
        nb::dict anchors, cover, regimes;
        for (int i = 0; i < NC; ++i) {
            anchors[COMM_NAMES[i]] = anchors_[i];
            cover[COMM_NAMES[i]] = cover_[i];
            regimes[COMM_NAMES[i]] = regime_[i] == REG_BOOM ? "boom"
                : regime_[i] == REG_BUST ? "bust" : "normal";
        }
        mkt["anchors"] = anchors; mkt["cover"] = cover;
        mkt["regimes"] = regimes;
        out["market"] = mkt;
    }
    if (equip_v2_) {
        nb::list stats;
        int64_t tot_fac = 0, tot_down = 0;
        for (auto& c : companies_) {
            const auto& st = equip_stats_[size_t(c.cid)];
            tot_fac += st.fac_ticks;
            tot_down += st.down_ticks;
            nb::dict sd;
            sd["name"] = c.name; sd["archetype"] = c.archetype;
            sd["fac_ticks"] = st.fac_ticks;
            sd["down_ticks"] = st.down_ticks;
            sd["breaks"] = st.breaks; sd["repairs"] = st.repairs;
            sd["maintenances"] = st.maintenances;
            sd["overhauls"] = st.overhauls;
            stats.append(sd);
        }
        nb::dict eq;
        eq["companies"] = stats;
        eq["fleet_fac_ticks"] = tot_fac;
        eq["fleet_down_ticks"] = tot_down;
        out["equipment"] = eq;
    }
    if (country_v2_) {
        nb::dict pol;
        for (auto& st : countries_) {
            nb::dict e;
            e["S"] = st.S; e["fx"] = st.fx; e["tau"] = st.tau;
            pol[pystr(st.name)] = e;
        }
        out["politics"] = pol;
        nb::dict tr;
        tr["money_to_external"] = money_to_external_;
        tr["money_from_external"] = money_from_external_;
        nb::dict imported, pimp, pexp;
        for (int i = 0; i < NC; ++i) {
            imported[COMM_NAMES[i]] = ledger_[i].imported;
            auto pr = parity(i);
            pimp[COMM_NAMES[i]] = pr.first;
            pexp[COMM_NAMES[i]] = pr.second;
        }
        tr["imported"] = imported;
        tr["parity_import"] = pimp;
        tr["parity_export"] = pexp;
        out["trade"] = tr;
    }
    return out;
}

nb::dict World::full_state() const {
    nb::dict out;
    out["seed"] = seed_;
    out["tick"] = tick_;
    {
        nb::list words;
        for (uint32_t w : rng.state_words()) words.append(int64_t(w));
        nb::list rs;
        rs.append(3);
        rs.append(words);
        if (rng.has_gauss()) rs.append(rng.gauss_next());
        else rs.append(nb::none());
        out["rng_state"] = rs;
    }
    nb::list cities;
    for (auto& c : cities_) {
        nb::dict cd;
        cd["name"] = c.name; cd["lat"] = c.lat; cd["lon"] = c.lon;
        cd["demand_weight"] = c.demand_weight;
        cities.append(cd);
    }
    out["cities"] = cities;
    nb::list deps;
    for (auto& d : deposits_) {
        nb::dict dd;
        dd["name"] = d.name; dd["resource"] = COMM_NAMES[d.resource];
        dd["lat"] = d.lat; dd["lon"] = d.lon;
        dd["size_t"] = d.size_t; dd["grade"] = d.grade;
        deps.append(dd);
    }
    out["deposits"] = deps;
    nb::dict remaining;
    for (size_t i = 0; i < deposits_.size(); ++i)
        remaining[pystr(deposits_[i].name)] = remaining_[i];
    out["remaining"] = remaining;
    nb::list claimed;
    for (auto& kv : claimed_by_) {
        nb::list cell; cell.append(kv.first.first);
        cell.append(kv.first.second);
        nb::list pair; pair.append(cell); pair.append(kv.second);
        claimed.append(pair);
    }
    out["claimed_by"] = claimed;
    nb::list comps;
    for (auto& c : companies_) {
        nb::dict cd;
        cd["cid"] = c.cid; cd["name"] = c.name;
        cd["archetype"] = c.archetype;
        nb::dict traits;
        traits["aggression"] = c.tr_aggr; traits["risk"] = c.tr_risk;
        traits["vertical"] = c.tr_vert; traits["marketing"] = c.tr_mkt;
        cd["traits"] = traits;
        cd["hq_city"] = c.hq_city; cd["color"] = c.color;
        cd["cash"] = c.cash;
        nb::dict stocks;
        for (int i = 0; i < NC; ++i) stocks[COMM_NAMES[i]] = c.stocks[i];
        cd["stocks"] = stocks;
        nb::dict facs;
        for (auto& f : c.facilities) {
            nb::dict fd;
            fd["id"] = f.id; fd["kind"] = FAC_NAMES[f.kind];
            nb::list cl; cl.append(f.cell_r); cl.append(f.cell_c);
            fd["cell"] = cl;
            if (f.deposit >= 0)
                fd["deposit"] = deposits_[size_t(f.deposit)].name;
            if (f.equip.present) {
                nb::dict eq;
                eq["age"] = f.equip.age; eq["cond"] = f.equip.cond;
                eq["down_until"] = f.equip.down_until;
                eq["broken"] = f.equip.broken;
                eq["repair_cost"] = f.equip.repair_cost;
                eq["repair_ticks"] = f.equip.repair_ticks;
                fd["equip"] = eq;
            }
            facs[pystr(f.id)] = fd;
        }
        cd["facilities"] = facs;
        nb::list cl_list;
        for (auto cell : c.claimed) {
            nb::list cl; cl.append(cell.first); cl.append(cell.second);
            cl_list.append(cl);
        }
        cd["claimed"] = cl_list;
        nb::dict know;
        for (auto& kv : c.knowledge) {
            nb::list v; v.append(kv.second.first);
            v.append(kv.second.second);
            know[pystr(kv.first)] = v;
        }
        cd["knowledge"] = know;
        nb::dict tools;
        tools["insta_until"] = c.insta_until;
        tools["insta_strength"] = c.insta_strength;
        tools["zap_until"] = c.zap_until;
        tools["vid_until"] = c.vid_until;
        tools["loja_until"] = c.loja_until;
        cd["tools"] = tools;
        cd["alive"] = c.alive;
        cd["founded_tick"] = 0;
        cd["fac_n"] = c.fac_n;
        comps.append(cd);
    }
    out["companies"] = comps;
    nb::dict prices;
    for (int i = 0; i < NC; ++i) prices[COMM_NAMES[i]] = prices_[i];
    out["prices"] = prices;
    nb::dict dfac;
    for (auto& kv : demand_factors_) {
        nb::list v; v.append(kv.second.first); v.append(kv.second.second);
        dfac[COMM_NAMES[kv.first]] = v;
    }
    out["demand_factors"] = dfac;
    nb::dict first_link;
    for (auto& kv : first_link_)
        first_link[pystr(std::to_string(kv.first))] = kv.second;
    out["first_link"] = first_link;
    nb::dict leaders;
    if (cash_leader_.has_value()) leaders["cash"] = *cash_leader_;
    else leaders["cash"] = nb::none();
    if (stage_leader_.has_value()) leaders["stage"] = *stage_leader_;
    else leaders["stage"] = nb::none();
    out["leaders"] = leaders;
    nb::dict super;
    for (auto& kv : super_by_cid_)
        super[pystr(std::to_string(kv.first))] = kv.second;
    out["super_by_cid"] = super;
    nb::dict spend_hist;
    for (auto& c : companies_) {
        if (c.spend_hist.empty()) continue;
        nb::dict h;
        for (auto& kv : c.spend_hist) {
            nb::list v; v.append(kv.second.first);
            v.append(kv.second.second);
            h[pystr(kv.first)] = v;
        }
        spend_hist[pystr(std::to_string(c.cid))] = h;
    }
    out["spend_hist"] = spend_hist;
    nb::dict ledger;
    for (int i = 0; i < NC; ++i) {
        nb::dict e;
        e["extracted"] = ledger_[i].extracted;
        e["produced"] = ledger_[i].produced;
        e["consumed"] = ledger_[i].consumed;
        e["wasted"] = ledger_[i].wasted;
        e["sold_external"] = ledger_[i].sold_external;
        if (country_v2_) e["imported"] = ledger_[i].imported;
        ledger[COMM_NAMES[i]] = e;
    }
    out["ledger_mass"] = ledger;
    out["initial_cash"] = initial_cash_;
    out["money_in"] = money_in_;
    out["money_out"] = money_out_;
    out["total_supercomputers"] = total_super_;
    if (market_v2_) {
        nb::dict blk;
        nb::dict anchors, regime, rmonths, ema, cover, noise, ring, rec;
        for (int i = 0; i < NC; ++i) {
            anchors[COMM_NAMES[i]] = anchors_[i];
            regime[COMM_NAMES[i]] = regime_[i] == REG_BOOM ? "boom"
                : regime_[i] == REG_BUST ? "bust" : "normal";
            rmonths[COMM_NAMES[i]] = regime_months_[i];
            ema[COMM_NAMES[i]] = demand_ema_[i];
            cover[COMM_NAMES[i]] = cover_[i];
            noise[COMM_NAMES[i]] = fair_noise_[i];
            nb::list r;
            for (double v : price_ring_[i]) r.append(v);
            ring[COMM_NAMES[i]] = r;
            nb::dict rs;
            if (record_dir_[i] == 1) rs["dir"] = "high";
            else if (record_dir_[i] == -1) rs["dir"] = "low";
            else rs["dir"] = nb::none();
            rs["extreme"] = record_extreme_[i];
            rec[COMM_NAMES[i]] = rs;
        }
        blk["anchors"] = anchors; blk["regime"] = regime;
        blk["regime_months"] = rmonths; blk["demand_ema"] = ema;
        blk["cover"] = cover; blk["fair_noise"] = noise;
        blk["price_ring"] = ring; blk["record_state"] = rec;
        out["market_block"] = blk;
    }
    if (equip_v2_) {
        nb::dict blk;
        nb::dict stats;
        for (auto& c : companies_) {
            const auto& st = equip_stats_[size_t(c.cid)];
            nb::dict sd;
            sd["fac_ticks"] = st.fac_ticks;
            sd["down_ticks"] = st.down_ticks;
            sd["breaks"] = st.breaks; sd["repairs"] = st.repairs;
            sd["maintenances"] = st.maintenances;
            sd["overhauls"] = st.overhauls;
            stats[pystr(std::to_string(c.cid))] = sd;
        }
        blk["stats"] = stats;
        out["equip_block"] = blk;
    }
    if (country_v2_) {
        nb::dict blk;
        nb::dict countries;
        for (auto& st : countries_) {
            nb::dict e;
            e["S"] = st.S; e["S_mean"] = st.S_mean;
            e["fx"] = st.fx; e["tau"] = st.tau;
            e["halt_until"] = st.halt_until;
            nb::dict restr;
            for (auto& kv : st.restrictions)
                restr[pystr(kv.first)] = kv.second;
            e["restrictions"] = restr;
            countries[pystr(st.name)] = e;
        }
        blk["countries"] = countries;
        blk["money_to_external"] = money_to_external_;
        blk["money_from_external"] = money_from_external_;
        nb::dict sur;
        for (auto& kv : parity_surcharge_)
            sur[COMM_NAMES[kv.first]] = kv.second;
        blk["parity_surcharge"] = sur;
        out["country_block"] = blk;
    }
    out["bankruptcies"] = bankruptcies_count_;
    return out;
}

// ------------------------------------------------------------------ //
// Importação de estado (restaura sem consumir RNG nem reemitir)      //
// ------------------------------------------------------------------ //
void World::import_state(const nb::dict& st, const nb::dict& cfg) {
    // configuração estática (parâmetros resolvidos) vem de cfg,
    // espelhando o construtor; o estado dinâmico vem de st (o
    // state_dict do motor Python, com os blocos das flags).
    seed_ = iget(st, "seed", 42);
    tick_ = iget(st, "tick", 0);
    {
        nb::list rs = nb::cast<nb::list>(st["rng_state"]);
        std::vector<uint32_t> words;
        for (auto w : nb::cast<nb::list>(rs[1]))
            words.push_back(uint32_t(nb::cast<int64_t>(w)));
        bool has_g = !rs[2].is_none();
        double g = has_g ? nb::cast<double>(rs[2]) : 0.0;
        rng.set_state(words, has_g, g);
    }
    deposits_.clear(); remaining_.clear(); cities_.clear();
    for (auto h : nb::cast<nb::list>(st["deposits"])) {
        nb::dict d = nb::cast<nb::dict>(h);
        Deposit dep;
        dep.name = sget(d, "name");
        dep.resource = comm_index(sget(d, "resource"));
        dep.lat = dget(d, "lat", 0); dep.lon = dget(d, "lon", 0);
        dep.size_t = dget(d, "size_t", 0); dep.grade = dget(d, "grade", 0);
        auto cell = cell_of(dep.lat, dep.lon);
        dep.cell_r = cell.first; dep.cell_c = cell.second;
        deposits_.push_back(dep);
    }
    {
        nb::dict rem = nb::cast<nb::dict>(st["remaining"]);
        for (auto& d : deposits_)
            remaining_.push_back(dget(rem, d.name.c_str(), 0));
    }
    for (auto h : nb::cast<nb::list>(st["cities"])) {
        nb::dict d = nb::cast<nb::dict>(h);
        City c;
        c.name = sget(d, "name"); c.lat = dget(d, "lat", 0);
        c.lon = dget(d, "lon", 0); c.demand_weight = dget(d, "demand_weight", 0);
        auto cell = cell_of(c.lat, c.lon);
        c.cell_r = cell.first; c.cell_c = cell.second;
        cities_.push_back(c);
    }
    claimed_by_.clear();
    for (auto h : nb::cast<nb::list>(st["claimed_by"])) {
        nb::list pair = nb::cast<nb::list>(h);
        nb::list cell = nb::cast<nb::list>(pair[0]);
        claimed_by_[{int(nb::cast<int64_t>(cell[0])),
                      int(nb::cast<int64_t>(cell[1]))}] =
            int(nb::cast<int64_t>(pair[1]));
    }
    parse_policy(nb::cast<nb::dict>(cfg["policy_params"]));
    market_v2_ = st.contains("market_v2");
    country_v2_ = st.contains("country_v2");
    equip_v2_ = st.contains("equip_v2");
    if (market_v2_)
        parse_market(nb::cast<nb::dict>(
            nb::cast<nb::dict>(st["market_v2"])["params"]));
    if (country_v2_)
        parse_country(nb::cast<nb::dict>(
            nb::cast<nb::dict>(st["country_v2"])["params"]));
    if (equip_v2_)
        parse_equip(nb::cast<nb::dict>(
            nb::cast<nb::dict>(st["equip_v2"])["params"]));
    companies_.clear();
    for (auto h : nb::cast<nb::list>(st["companies"])) {
        nb::dict cs = nb::cast<nb::dict>(h);
        Company c;
        c.cid = int(iget(cs, "cid", 0));
        c.name = sget(cs, "name");
        c.archetype = sget(cs, "archetype");
        nb::dict tr = nb::cast<nb::dict>(cs["traits"]);
        c.tr_aggr = dget(tr, "aggression", 0);
        c.tr_risk = dget(tr, "risk", 0);
        c.tr_vert = dget(tr, "vertical", 0);
        c.tr_mkt = dget(tr, "marketing", 0);
        c.hq_city = sget(cs, "hq_city");
        c.color = sget(cs, "color");
        c.cash = dget(cs, "cash", 0);
        nb::dict stocks = nb::cast<nb::dict>(cs["stocks"]);
        for (int i = 0; i < NC; ++i)
            c.stocks[i] = dget(stocks, COMM_NAMES[i], 0);
        nb::dict facs = nb::cast<nb::dict>(cs["facilities"]);
        for (auto item : facs) {   // dict: ordem de inserção
            nb::dict f = nb::cast<nb::dict>(item.second);
            Facility fac;
            fac.id = sget(f, "id");
            fac.kind = fac_index(sget(f, "kind"));
            nb::list cell = nb::cast<nb::list>(f["cell"]);
            fac.cell_r = int(nb::cast<int64_t>(cell[0]));
            fac.cell_c = int(nb::cast<int64_t>(cell[1]));
            if (f.contains("deposit"))
                fac.deposit = deposit_idx(sget(f, "deposit"));
            if (f.contains("equip")) {
                nb::dict eq = nb::cast<nb::dict>(f["equip"]);
                fac.equip.present = true;
                fac.equip.age = iget(eq, "age", 0);
                fac.equip.cond = dget(eq, "cond", 1.0);
                fac.equip.down_until = iget(eq, "down_until", -1);
                fac.equip.broken = nb::cast<bool>(eq["broken"]);
                fac.equip.repair_cost = dget(eq, "repair_cost", 0);
                fac.equip.repair_ticks = iget(eq, "repair_ticks", 0);
            }
            c.facilities.push_back(fac);
            c.kinds_mask |= (1u << fac.kind);
        }
        for (auto h2 : nb::cast<nb::list>(cs["claimed"])) {
            nb::list cell = nb::cast<nb::list>(h2);
            c.claimed.insert({int(nb::cast<int64_t>(cell[0])),
                              int(nb::cast<int64_t>(cell[1]))});
        }
        nb::dict know = nb::cast<nb::dict>(cs["knowledge"]);
        for (auto item : know) {
            nb::list v = nb::cast<nb::list>(item.second);
            c.knowledge[nb::cast<std::string>(item.first)] =
                {nb::cast<double>(v[0]), nb::cast<double>(v[1])};
        }
        nb::dict tools = nb::cast<nb::dict>(cs["tools"]);
        c.insta_until = iget(tools, "insta_until", -1);
        c.insta_strength = dget(tools, "insta_strength", 0);
        c.zap_until = iget(tools, "zap_until", -1);
        c.vid_until = iget(tools, "vid_until", -1);
        c.loja_until = iget(tools, "loja_until", -1);
        c.alive = nb::cast<bool>(cs["alive"]);
        c.fac_n = iget(cs, "fac_n", 0);
        companies_.push_back(std::move(c));
    }
    {
        nb::dict sh = nb::cast<nb::dict>(st["spend_hist"]);
        for (auto item : sh) {
            int cid = std::stoi(nb::cast<std::string>(item.first));
            nb::dict h = nb::cast<nb::dict>(item.second);
            for (auto r : h) {
                nb::list v = nb::cast<nb::list>(r.second);
                companies_[size_t(cid)].spend_hist[
                    nb::cast<std::string>(r.first)] =
                    {nb::cast<double>(v[0]), nb::cast<int64_t>(v[1])};
            }
        }
    }
    {
        nb::dict prices = nb::cast<nb::dict>(st["prices"]);
        for (int i = 0; i < NC; ++i)
            prices_[i] = dget(prices, COMM_NAMES[i], 0);
        nb::dict dfac = nb::cast<nb::dict>(st["demand_factors"]);
        demand_factors_.clear();
        for (auto item : dfac) {
            nb::list v = nb::cast<nb::list>(item.second);
            demand_factors_[comm_index(nb::cast<std::string>(
                item.first))] = {nb::cast<double>(v[0]),
                                nb::cast<int64_t>(v[1])};
        }
        nb::dict fl = nb::cast<nb::dict>(st["first_link"]);
        first_link_.clear();
        for (auto item : fl)
            first_link_[std::stoi(nb::cast<std::string>(item.first))] =
                nb::cast<std::string>(item.second);
        nb::dict ld = nb::cast<nb::dict>(st["leaders"]);
        cash_leader_ = ld["cash"].is_none() ? std::nullopt
            : std::optional<int>(int(nb::cast<int64_t>(ld["cash"])));
        stage_leader_ = ld["stage"].is_none() ? std::nullopt
            : std::optional<int>(int(nb::cast<int64_t>(ld["stage"])));
        nb::dict sb = nb::cast<nb::dict>(st["super_by_cid"]);
        super_by_cid_.clear();
        for (auto item : sb)
            super_by_cid_.emplace_back(
                std::stoi(nb::cast<std::string>(item.first)),
                nb::cast<double>(item.second));
        nb::dict ledger = nb::cast<nb::dict>(st["ledger_mass"]);
        for (int i = 0; i < NC; ++i) {
            nb::dict e = nb::cast<nb::dict>(ledger[COMM_NAMES[i]]);
            ledger_[i].extracted = dget(e, "extracted", 0);
            ledger_[i].produced = dget(e, "produced", 0);
            ledger_[i].consumed = dget(e, "consumed", 0);
            ledger_[i].wasted = dget(e, "wasted", 0);
            ledger_[i].sold_external = dget(e, "sold_external", 0);
            ledger_[i].imported = dget(e, "imported", 0);
        }
    }
    initial_cash_ = dget(st, "initial_cash", 0);
    money_in_ = dget(st, "money_in", 0);
    money_out_ = dget(st, "money_out", 0);
    total_super_ = dget(st, "total_supercomputers", 0);
    anchors_ = BASE_PRICES;
    if (market_v2_) {
        nb::dict blk = nb::cast<nb::dict>(st["market_v2"]);
        nb::dict anchors = nb::cast<nb::dict>(blk["anchors"]);
        nb::dict regime = nb::cast<nb::dict>(blk["regime"]);
        nb::dict rmonths = nb::cast<nb::dict>(blk["regime_months"]);
        nb::dict ema = nb::cast<nb::dict>(blk["demand_ema"]);
        nb::dict cover = nb::cast<nb::dict>(blk["cover"]);
        nb::dict noise = nb::cast<nb::dict>(blk["fair_noise"]);
        nb::dict ring = nb::cast<nb::dict>(blk["price_ring"]);
        nb::dict rec = nb::cast<nb::dict>(blk["record_state"]);
        for (int i = 0; i < NC; ++i) {
            anchors_[i] = dget(anchors, COMM_NAMES[i], 0);
            std::string rg = sget(regime, COMM_NAMES[i]);
            regime_[i] = rg == "boom" ? REG_BOOM
                         : rg == "bust" ? REG_BUST : REG_NORMAL;
            regime_months_[i] = iget(rmonths, COMM_NAMES[i], 0);
            demand_ema_[i] = dget(ema, COMM_NAMES[i], 0);
            cover_[i] = dget(cover, COMM_NAMES[i], 0);
            fair_noise_[i] = dget(noise, COMM_NAMES[i], 0);
            price_ring_[i].clear();
            for (auto v : nb::cast<nb::list>(ring[COMM_NAMES[i]]))
                price_ring_[i].push_back(nb::cast<double>(v));
            nb::dict rs = nb::cast<nb::dict>(rec[COMM_NAMES[i]]);
            if (rs["dir"].is_none()) record_dir_[i] = 0;
            else record_dir_[i] = sget(rs, "dir") == "high" ? 1 : -1;
            record_extreme_[i] = dget(rs, "extreme", 0);
        }
    }
    if (equip_v2_) {
        nb::dict blk = nb::cast<nb::dict>(st["equip_v2"]);
        nb::dict stats = nb::cast<nb::dict>(blk["stats"]);
        equip_stats_.assign(companies_.size(), EquipStats{});
        for (auto item : stats) {
            int cid = std::stoi(nb::cast<std::string>(item.first));
            nb::dict sd = nb::cast<nb::dict>(item.second);
            auto& s = equip_stats_[size_t(cid)];
            s.fac_ticks = iget(sd, "fac_ticks", 0);
            s.down_ticks = iget(sd, "down_ticks", 0);
            s.breaks = iget(sd, "breaks", 0);
            s.repairs = iget(sd, "repairs", 0);
            s.maintenances = iget(sd, "maintenances", 0);
            s.overhauls = iget(sd, "overhauls", 0);
        }
    }
    if (country_v2_) {
        nb::dict blk = nb::cast<nb::dict>(st["country_v2"]);
        nb::dict countries = nb::cast<nb::dict>(blk["countries"]);
        std::vector<std::string> names;
        for (auto item : countries)
            names.push_back(nb::cast<std::string>(item.first));
        std::sort(names.begin(), names.end());
        countries_.clear();
        country_idx_.clear();
        for (auto& name : names) {
            nb::dict e = nb::cast<nb::dict>(countries[pystr(name)]);
            Country cst;
            cst.name = name;
            cst.S = dget(e, "S", 0);
            cst.S_mean = dget(e, "S_mean", 0);
            cst.fx = dget(e, "fx", 0);
            cst.tau = dget(e, "tau", 0);
            cst.halt_until = iget(e, "halt_until", -1);
            nb::dict restr = nb::cast<nb::dict>(e["restrictions"]);
            for (auto r : restr)
                cst.restrictions[nb::cast<std::string>(r.first)] =
                    nb::cast<int64_t>(r.second);
            country_idx_[name] = countries_.size();
            countries_.push_back(std::move(cst));
        }
        election_offset_.clear();
        int64_t i = 0;
        for (auto& cst : countries_)
            election_offset_[cst.name] =
                (i++) * ctry_.model.election_stagger;
        money_to_external_ = dget(blk, "money_to_external", 0);
        money_from_external_ = dget(blk, "money_from_external", 0);
        parity_surcharge_.clear();
        nb::dict sur = nb::cast<nb::dict>(blk["parity_surcharge"]);
        for (auto item : sur)
            parity_surcharge_[comm_index(nb::cast<std::string>(
                item.first))] = nb::cast<double>(item.second);
    }
    bankruptcies_count_ = iget(cfg, "bankruptcies", 0);
    flows_.assign(companies_.size(), {});
    royalty_due_.clear();
    capex_memo_.clear();
    dep_country_cache_.clear();
    resources_dirty_ = true;
}

NB_MODULE(_native, m) {
    m.def("available", []() { return true; });
    nb::class_<World>(m, "World")
        .def(nb::init<const nb::dict&>())
        .def("step", &World::step)
        .def("frame", &World::frame_data)
        .def("result_data", &World::result_data)
        .def("full_state", &World::full_state)
        .def("import_state", &World::import_state)
        .def("get_tick", [](const World& w) { return w.tick_; });
    m.def("make_world", [](const nb::dict& cfg) { return World(cfg); });
    m.def("restore_world", [](const nb::dict& st, const nb::dict& cfg) {
        World w;
        w.import_state(st, cfg);
        return w;
    });
}
