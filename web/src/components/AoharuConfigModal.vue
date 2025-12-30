<template>
  <div id="aoharu-config-modal" class="modal fade" data-backdrop="static" data-keyboard="false">
    <div class="modal-dialog modal-dialog-centered modal-xl">
      <div class="modal-content" @click.stop>
        <div class="modal-header d-flex align-items-center justify-content-between">
          <h5 class="mb-0">Aoharu Cup Configuration</h5>
          <div>
            <button class="btn btn-sm btn-outline-secondary me-2" @click="$emit('update:show', false)">Cancel</button>
            <button class="btn btn-sm btn--primary" @click="confirm">Confirm</button>
          </div>
        </div>
        <div class="modal-body">
          <div class="row">
            <div class="col-5 section-card p-3">
              <h6 class="mb-3">Select Preliminary Round Participants</h6>
              <div class="form-group">
                <label>Preliminary Round 1&nbsp;&nbsp;</label>
                <div class="form-check form-check-inline">
                  <input class="form-check-input" type="radio" id="pr1_1" :value="1" v-model.number="internalPreliminaryRoundSelections[0]">
                  <label class="form-check-label" for="pr1_1">1</label>
                </div>
                <div class="form-check form-check-inline">
                  <input class="form-check-input" type="radio" id="pr1_2" :value="2" v-model.number="internalPreliminaryRoundSelections[0]">
                  <label class="form-check-label" for="pr1_2">2</label>
                </div>
                <div class="form-check form-check-inline">
                  <input class="form-check-input" type="radio" id="pr1_3" :value="3" v-model.number="internalPreliminaryRoundSelections[0]">
                  <label class="form-check-label" for="pr1_3">3</label>
                </div>
              </div>
              <div class="form-group">
                <label>Preliminary Round 2&nbsp;&nbsp;</label>
                <div class="form-check form-check-inline">
                  <input class="form-check-input" type="radio" id="pr2_1" :value="1" v-model.number="internalPreliminaryRoundSelections[1]">
                  <label class="form-check-label" for="pr2_1">1</label>
                </div>
                <div class="form-check form-check-inline">
                  <input class="form-check-input" type="radio" id="pr2_2" :value="2" v-model.number="internalPreliminaryRoundSelections[1]">
                  <label class="form-check-label" for="pr2_2">2</label>
                </div>
                <div class="form-check form-check-inline">
                  <input class="form-check-input" type="radio" id="pr2_3" :value="3" v-model.number="internalPreliminaryRoundSelections[1]">
                  <label class="form-check-label" for="pr2_3">3</label>
                </div>
              </div>
              <div class="form-group">
                <label>Preliminary Round 3&nbsp;&nbsp;</label>
                <div class="form-check form-check-inline">
                  <input class="form-check-input" type="radio" id="pr3_1" :value="1" v-model.number="internalPreliminaryRoundSelections[2]">
                  <label class="form-check-label" for="pr3_1">1</label>
                </div>
                <div class="form-check form-check-inline">
                  <input class="form-check-input" type="radio" id="pr3_2" :value="2" v-model.number="internalPreliminaryRoundSelections[2]">
                  <label class="form-check-label" for="pr3_2">2</label>
                </div>
                <div class="form-check form-check-inline">
                  <input class="form-check-input" type="radio" id="pr3_3" :value="3" v-model.number="internalPreliminaryRoundSelections[2]">
                  <label class="form-check-label" for="pr3_3">3</label>
                </div>
              </div>
              <div class="form-group">
                <label>Preliminary Round 4&nbsp;&nbsp;</label>
                <div class="form-check form-check-inline">
                  <input class="form-check-input" type="radio" id="pr4_1" :value="1" v-model.number="internalPreliminaryRoundSelections[3]">
                  <label class="form-check-label" for="pr4_1">1</label>
                </div>
                <div class="form-check form-check-inline">
                  <input class="form-check-input" type="radio" id="pr4_2" :value="2" v-model.number="internalPreliminaryRoundSelections[3]">
                  <label class="form-check-label" for="pr4_2">2</label>
                </div>
                <div class="form-check form-check-inline">
                  <input class="form-check-input" type="radio" id="pr4_3" :value="3" v-model.number="internalPreliminaryRoundSelections[3]">
                  <label class="form-check-label" for="pr4_3">3</label>
                </div>
              </div>
            </div>
            <div class="col-7 section-card p-3">
              <h6 class="mb-3">Select Aoharu Team Name</h6>
              <div class="form-group">
                <div class="form-check mb-3 ps-0">
                  <input class="form-check-input" type="radio" id="team_taiki" :value="0" v-model.number="internalAoharuTeamNameSelection">
                  <label class="form-check-label" for="team_taiki">Taiki Shuttle &lt;HOP CHEERS&gt; <SkillIcon name="Mile Dominator" type="speed"></SkillIcon></label>
                </div>
                <div class="form-check mb-3 ps-0">
                  <input class="form-check-input" type="radio" id="team_fukukitaru" :value="1" v-model.number="internalAoharuTeamNameSelection">
                  <label class="form-check-label" for="team_fukukitaru">Matikanefukukitaru &lt;Sunny Runner&gt; <SkillIcon name="Eagle Eye" type="sight"></SkillIcon></label>
                </div>
                <div class="form-check mb-3 ps-0">
                  <input class="form-check-input" type="radio" id="team_urara" :value="2" v-model.number="internalAoharuTeamNameSelection">
                  <label class="form-check-label" for="team_urara">Haru Urara &lt;Carrot Pudding&gt; <SkillIcon name="Unyielding Heart" type="stamina"></SkillIcon></label>
                </div>
                <div class="form-check mb-3 ps-0">
                  <input class="form-check-input" type="radio" id="team_raisu" :value="3" v-model.number="internalAoharuTeamNameSelection">
                  <label class="form-check-label" for="team_raisu">Rice Shower &lt;Bloom&gt; <SkillIcon name="Cooldown" type="stamina"></SkillIcon></label>
                </div>
                <div class="form-check mb-3 ps-0">
                  <input class="form-check-input" type="radio" id="team_default" :value="4" v-model.number="internalAoharuTeamNameSelection">
                  <label class="form-check-label" for="team_default">Default &lt;Carrot&gt; <SkillIcon name="Non‑stop Girl" type="accelerate"></SkillIcon></label>
                </div>
              </div>
            </div>
          </div>
        </div>
        <div class="modal-footer d-none"></div>
      </div>
    </div>
  </div>
</template>

<script>
import SkillIcon from './SkillIcon.vue';

export default {
  name: 'AoharuConfigModal',
  components: {
    SkillIcon
  },
  props: {
    show: Boolean,
    preliminaryRoundSelections: {
      type: Array,
      default: () => [2, 1, 1, 1]
    },
    aoharuTeamNameSelection: {
      type: Number,
      default: 4
    },
  },
  emits: ['update:show', 'confirm'],
  data() {
    return {
      // Internal data for the modal, initialized from props
      internalPreliminaryRoundSelections: [...this.preliminaryRoundSelections],
      internalAoharuTeamNameSelection: this.aoharuTeamNameSelection,
    };
  },
  watch: {
    show(newVal) {
      if (newVal) {
        // When show becomes true, display the modal
        $('#aoharu-config-modal').modal({
          backdrop: 'static',
          keyboard: false,
          show: true
        });
      } else {
        // When show becomes false, hide the modal
        $('#aoharu-config-modal').modal('hide');
      }
    },
    // Watch for changes in props and update internal data
    preliminaryRoundSelections: {
      handler(newVal) {
        this.internalPreliminaryRoundSelections = [...newVal];
      },
      deep: true
    },
    aoharuTeamNameSelection(newVal) { this.internalAoharuTeamNameSelection = newVal; },
  },
  methods: {
    confirm() {
      // Emit the updated values back to the parent
      this.$emit('confirm', {
        preliminaryRoundSelections: this.internalPreliminaryRoundSelections.map(Number),
        aoharuTeamNameSelection: Number(this.internalAoharuTeamNameSelection),
      });
      this.$emit('update:show', false); // Close the modal
      
      // 确保父modal的滚动功能在关闭时得到恢复
      this.$nextTick(() => {
        this.restoreParentModalScrolling();
      });
    },
    restoreParentModalScrolling() {
      // 恢复父modal的滚动功能
      setTimeout(() => {
        if ($('.modal-open').length > 0) {
          $('body').addClass('modal-open');
          const parentModal = $('#create-task-list-modal');
          if (parentModal.hasClass('show')) {
            const modalBody = parentModal.find('.modal-body');
            if (modalBody.length > 0) {
              modalBody.css('overflow-y', 'auto');
              // 强制触发重新渲染
              modalBody[0].offsetHeight;
            }
          }
        }
      }, 100);
    },
  },
  mounted() {
    // Initialize Bootstrap modal behavior
    $('#aoharu-config-modal').on('hidden.bs.modal', () => {
      this.$emit('update:show', false);
      // 确保父modal保持滚动功能
      this.$nextTick(() => {
        this.restoreParentModalScrolling();
      });
    });
  }
};
</script>

<style scoped>
/* 确保青春杯配置modal在最顶层 */
#aoharu-config-modal.modal {
  z-index: 1060; /* 比TaskEditModal和遮罩层更高 */
}

#aoharu-config-modal .modal-dialog {
  z-index: 1061;
}

/* 放大确认按钮 */
.confirm-btn-large {
  padding: 0.5rem 1rem !important;
  font-size: 1rem !important;
  font-weight: 400 !important;
  min-width: 60px;
  min-height: 40px;
}

/* 修复单选框和文字对齐问题 */
#aoharu-config-modal .section-card{border:1px solid var(--accent);border-radius:12px;box-shadow:none}

.form-check {
  display: flex;
  align-items: center;
}

/* 左侧预赛选手 - 保持inline布局 */
.form-check-inline {
  display: inline-flex !important;
  align-items: center;
  margin-right: 1rem;
}

/* 右侧队名选择 - 每个选项占一行 */
.form-check.mb-3 {
  display: flex !important;
  align-items: center;
  margin-bottom: 1rem !important;
}

.form-check-input {
  margin-top: 0 !important;
  margin-right: 8px;
  flex-shrink: 0;
}

.form-check-label {
  margin-bottom: 0;
  line-height: 1.4;
  display: flex;
  align-items: center;
}

/* 确保技能图标也垂直居中 */
.form-check-label > * {
  vertical-align: middle;
}
</style>
