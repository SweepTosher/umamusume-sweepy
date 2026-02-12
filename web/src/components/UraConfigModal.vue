<template>
  <div id="ura-config-modal" class="modal fade" data-backdrop="static" data-keyboard="false">
    <div class="modal-dialog modal-dialog-centered modal-xl">
      <div class="modal-content" @click.stop>
        <div class="modal-header d-flex align-items-center justify-content-between">
          <h5 class="mb-0">URA Configuration</h5>
          <div>
            <button class="btn btn-sm btn-outline-secondary me-2" @click="cancel">Cancel</button>
            <button class="btn btn-sm btn--primary" @click="confirm">Confirm</button>
          </div>
        </div>
        <div class="modal-body">
          <!-- Support Card Inspiration Additional Weight -->
          <div class="form-group section-card p-3 mb-3">
            <h6 class="mb-2"><b>(Test)</b> Support Card Inspiration (!) Additional Weight</h6>
            <p>Additional weight provided for training selection when support cards show inspiration (!). Multiple exclamation marks in a single training only count once.</p>
            <p>Settable range [0, 1]. 0 means support card inspiration has no impact on training selection, 1 means always choose training with inspiration.</p>
            <div class="row">
              <div class="col-4">
                <div class="form-group">
                  <label for="ura-year1-skill-event-weight">Year 1</label>
                  <input 
                    type="number" 
                    v-model="internalSkillEventWeight[0]" 
                    class="form-control" 
                    id="ura-year1-skill-event-weight"
                    @input="onWeightInput(0)"
                    step="0.1"
                    min="0"
                    max="1"
                  >
                </div>
              </div>
              <div class="col-4">
                <div class="form-group">
                  <label for="ura-year2-skill-event-weight">Year 2</label>
                  <input 
                    type="number" 
                    v-model="internalSkillEventWeight[1]" 
                    class="form-control" 
                    id="ura-year2-skill-event-weight"
                    @input="onWeightInput(1)"
                    step="0.1"
                    min="0"
                    max="1"
                  >
                </div>
              </div>
              <div class="col-4">
                <div class="form-group">
                  <label for="ura-year3-skill-event-weight">Year 3</label>
                  <input 
                    type="number" 
                    v-model="internalSkillEventWeight[2]" 
                    class="form-control" 
                    id="ura-year3-skill-event-weight"
                    @input="onWeightInput(2)"
                    step="0.1"
                    min="0"
                    max="1"
                  >
                </div>
              </div>
            </div>
          </div>
          
          <!-- Reset Skill Inspiration Weight Configuration -->
          <div class="form-group section-card p-3">
            <label for="ura-reset-skill-event-weight-list">Reset skill inspiration weight to 0 after learning these skills</label>
            <textarea 
              type="text" 
              v-model="internalResetSkillEventWeightList" 
              class="form-control" 
              id="ura-reset-skill-event-weight-list" 
              placeholder="Corner Acceleration ◯, Slipstream, Speed Star, ... (use commas)"
              rows="3"
            ></textarea>
          </div>
        </div>
        <div class="modal-footer d-none"></div>
      </div>
    </div>
  </div>
</template>

<script>
export default {
  name: 'UraConfigModal',
  props: {
    show: Boolean,
    skillEventWeight: {
      type: Array,
      default: () => [0, 0, 0]
    },
    resetSkillEventWeightList: {
      type: String,
      default: ''
    },
  },
  emits: ['update:show', 'confirm'],
  data() {
    return {
      internalSkillEventWeight: [...this.skillEventWeight],
      internalResetSkillEventWeightList: this.resetSkillEventWeightList
    };
  },
  watch: {
    show(newVal) {
      if (newVal) {
        // When show becomes true, display the modal
        $('#ura-config-modal').modal({
          backdrop: 'static',
          keyboard: false,
          show: true
        });
      } else {
        // When show becomes false, hide the modal
        $('#ura-config-modal').modal('hide');
      }
    },
    skillEventWeight: {
      handler(newVal) {
        this.internalSkillEventWeight = [...newVal];
      },
      deep: true
    },
    resetSkillEventWeightList(newVal) { 
      this.internalResetSkillEventWeightList = newVal; 
    },
  },
  methods: {
    onWeightInput(index) {
      // Limit input range [0, 1]
      let value = parseFloat(this.internalSkillEventWeight[index]);
      if (value > 1) {
        this.internalSkillEventWeight[index] = 1;
      } else if (value < 0) {
        this.internalSkillEventWeight[index] = 0;
      }
    },
    confirm() {
      // Emit the updated values back to the parent
      this.$emit('confirm', {
        skillEventWeight: this.internalSkillEventWeight.map(Number),
        resetSkillEventWeightList: this.internalResetSkillEventWeightList,
      });
      this.$emit('update:show', false);
      
      this.$nextTick(() => {
        this.restoreParentModalScrolling();
      });
    },
    cancel() {
      this.$emit('update:show', false);
      this.$emit('cancel');
      
      // Ensure parent modal scroll function is restored when closed
      this.$nextTick(() => {
        this.restoreParentModalScrolling();
      });
    },
    restoreParentModalScrolling() {
      // Restore parent modal scroll function
      setTimeout(() => {
        if ($('.modal-open').length > 0) {
          $('body').addClass('modal-open');
          const parentModal = $('#create-task-list-modal');
          if (parentModal.hasClass('show')) {
            const modalBody = parentModal.find('.modal-body');
            if (modalBody.length > 0) {
              modalBody.css('overflow-y', 'auto');
              // Force trigger re-render
              modalBody[0].offsetHeight;
            }
          }
        }
      }, 100);
    },
  },
  mounted() {
    // Initialize Bootstrap modal behavior
    $('#ura-config-modal').on('hidden.bs.modal', () => {
      this.$emit('update:show', false);
      // Ensure parent modal maintains scroll function
      this.$nextTick(() => {
        this.restoreParentModalScrolling();
      });
    });
  }
};
</script>

<style scoped>
/* Ensure URA config modal is at the top layer */
#ura-config-modal.modal {
  z-index: 1060; /* Higher than TaskEditModal and overlay */
}

#ura-config-modal .modal-dialog {
  z-index: 1061;
}

.section-card{border:1px solid var(--accent);border-radius:12px;box-shadow:none;}

/* Enlarge confirm button */
/* header buttons reuse global theme classes */
</style>
