<template>
  <div id="support-card-select-modal" class="modal fade" data-backdrop="static" data-keyboard="false">
    <div class="modal-dialog modal-dialog-centered modal-xl">
      <div class="modal-content" @click.stop>
        <div class="modal-header d-flex align-items-center justify-content-between">
          <h5 class="mb-0">Borrowing Support Card</h5>
          <div>
            <button class="btn btn-sm btn-outline-secondary me-2" @click="handleCancel">Cancel</button>
            <button class="btn btn-sm btn--primary" @click="handleConfirm" :disabled="isConfirmDisabled">Confirm</button>
          </div>
        </div>
        <div class="modal-body support-card-modal-body">
          <div class="section-card p-3 mb-2">
          <div class="type-btn-row">
            <button
              v-for="type in supportCardTypes"
              :key="type.name"
              type="button"
              class="type-btn"
              :class="[ { active: activeType === type.name }, type.name === 'custom' ? 'custom-btn' : '' ]"
              @click="setActiveType(type.name)"
              >
              <template v-if="type.name !== 'custom'">
                <img v-if="type.img" :src="type.img" :alt="type.name" class="type-btn-img" />
              </template>
              <template v-else>
                <span class="type-btn-text">Custom</span>
              </template>
            </button>
          </div>
          <hr class="type-btn-divider"/>
          <!-- 支援卡图片展示区域 -->
          <div v-if="activeType !== 'custom'" class="support-card-img-grid mt-3">
            <div v-for="row in filteredCardImageRows" :key="row[0].id" class="img-row">
              <div
                v-for="card in row"
                :key="card.id"
                class="img-cell"
                :style="{ flex: '0 0 12.5%' }"
              >
                <div class="img-content">
                  <div
                    class="card-img-wrapper"
                    :class="{ 'selected-card': selectedCard && selectedCard.id === card.id }"
                    @click="selectCard(card)"
                    style="cursor: pointer;"
                  >
                    <img
                      :src="getCardImgUrl(card.id)"
                      :alt="card.name"
                      class="support-card-img"
                      :title="renderSupportCardText(card)"
                      @error="handleImgError"
                    />
                    <!-- 左上角SSR图标 -->
                    <img
                      :src="getRarityIcon('SSR')"
                      class="card-ssr-icon"
                      alt="SSR"
                    />
                    <!-- 右上角类型图标 -->
                    <img
                      :src="getTypeIcon(card.id)"
                      class="card-type-icon"
                      alt="type"
                    />
                  </div>
                  <div class="support-card-label">
                    {{ renderSupportCardTextEllipsis(card) }}
                  </div>
                </div>
              </div>
              <!-- 补齐空位，保证最后一行图片对齐 -->
              <div
                v-for="n in (8 - row.length)"
                :key="'empty-'+n"
                class="img-cell"
                :style="{ flex: '0 0 12.5%' }"
              ></div>
            </div>
          </div>
          <div v-if="activeType === 'custom'" class="mt-3">
            <input type="text" class="form-control" placeholder="Enter card name here example 'Planned Perfection' or 'Fire at My Heels'" v-model="customCardName">
          </div>
          <p class="chinese-disclaimer">Yes I know some of the cards are in chinese and no im not gonna fix it. Just type their names in custom tab</p>
          </div>
        </div>
        <div class="modal-footer d-none"></div>
      </div>
    </div>
  </div>
</template>

<script>
export default {
  name: "SupportCardSelectModal",
  props: {
    show: {
      type: Boolean,
      required: true
    }
  },
  emits: ['update:show', 'cancel', 'confirm'],
  data() {
    return {
      umamusumeSupportCardList:         [
          {id:10001, name:"Beyond This Shining Moment", desc:"Silence Suzuka"},
          {id:10002, name:"Dream Big!", desc:"Tokai Teio"},
          {id:10003, name:"Run (my) way", desc:"Gold City"},
          {id:10004, name:"Eat Fast! Yum Fast!", desc:"Sakura Bakushin O"},
          {id:10005, name:"Even the Littlest Bud", desc:"Nishino Flower"},
          {id:10006, name:"Double Carrot Punch!", desc:"Biko Pegasus"},
          {id:10007, name:"The Setting Sun and Rising Stars", desc:"Special Week"},
          {id:10008, name:"Turbo Booooost!", desc:"Twin Turbo"},
          {id:10009, name:"Fire at My Heels", desc:"Kitasan Black"},
          {id:10010, name:"Princess Bride", desc:"Kawakami Princess"},
          {id:10011, name:"Two Pieces", desc:"Narita Brian"},
          {id:10012, name:"It's All Mine!", desc:"Sweep Tosho"},
          {id:10013, name:"That Time I Became the Strongest", desc:"Gold Ship"},
          {id:10014, name:"被授予魔力的英雄", desc:"Zenno Rob Roy"},
          {id:10015, name:"队形: PARTY", desc:"Mayano Top Gun"},
          {id:10016, name:"追寻未曾见过的景色", desc:"Silence Suzuka"},
          {id:10017, name:"萍水相逢即是福", desc:"Matikanefukukitaru"},
          {id:10018, name:"In my way", desc:"Tosen Jordan"},
          {id:20001, name:"Breakaway Battleship", desc:"Gold Ship"},
          {id:20002, name:"Foolproof Plan", desc:"Seiun Sky"},
          {id:20003, name:"Split the Sky, White Lightning!", desc:"Tamamo Cross"},
          {id:20004, name:"Piece of Mind", desc:"Super Creek"},
          {id:20005, name:"Your Team Ace", desc:"Mejiro McQueen"},
          {id:20006, name:"Showered in Joy", desc:"Rice Shower"},
          {id:20007, name:"The Will to Overtake", desc:"Satono Diamond"},
          {id:20008, name:"Peak Sakura Season", desc:"Sakura Chiyono O"},
          {id:20009, name:"43、8、1", desc:"Nakayama Festa"},
          {id:20010, name:"Full-Blown Tantrum", desc:"Winning Ticket"},
          {id:20011, name:"Winning Dream", desc:"Silence Suzuka"},
          {id:20012, name:"鸣箭嗤天", desc:"Narita Brian"},
          {id:20013, name:"独奏·螺旋卡农", desc:"Manhattan Cafe"},
          {id:20014, name:"想要飞奔而出的心情", desc:"Meisho Doto"},
          {id:30001, name:"Wild Rider", desc:"Vodka"},
          {id:30002, name:"Champion's Passion", desc:"El Condor Pasa"},
          {id:30003, name:"My Umadol Way! ☆", desc:"Smart Falcon"},
          {id:30004, name:"Get Lots of Hugs for Me", desc:"Oguri Cap"},
          {id:30005, name:"Fiery Discipline", desc:"Yaeno Muteki"},
          {id:30006, name:"Dreams Do Come True!", desc:"Winning Ticket"},
          {id:30007, name:"Happiness Just around the Bend", desc:"Rice Shower"},
          {id:30008, name:"Head-On Fight!", desc:"Bamboo Memory"},
          {id:30009, name:"Mini☆Vacation", desc:"Daiwa Scarlet"},
          {id:30010, name:"Tonight, We Waltz", desc:"King Halo"},
          {id:30011, name:"大闹万圣夜！", desc:"Tamamo Cross"},
          {id:30012, name:"舞动吧·躁动吧·狂欢吧！", desc:"Daitaku Helios"},
          {id:30013, name:"冰晶之日", desc:"Marvelous Sunday"},
          {id:30014, name:"夜有黎明，天有祥星", desc:"Admire Vega"},
          {id:30015, name:"存在于此的幸福", desc:"Agnes Digital"},
          {id:40001, name:"The Brightest Star in Japan", desc:"Special Week"},
          {id:40002, name:"Fairest Fleur", desc:"Grass Wonder"},
          {id:40003, name:"Watch My Star Fly!", desc:"Ines Fujin"},
          {id:40004, name:"BNWinner!", desc:"Winning Ticket"},
          {id:40005, name:"Urara's Day Off!", desc:"Haru Urara"},
          {id:40006, name:"Go Ahead and Laugh", desc:"Mejiro Palmer"},
          {id:40007, name:"Just Keep Going", desc:"Matikane Tannhauser"},
          {id:40008, name:"Who Wants the First Bite?", desc:"Hishi Akebono"},
          {id:40009, name:"Winning Pitch", desc:"Mejiro Ryan"},
          {id:40010, name:"内心双脚皆温暖", desc:"Ikuno Dictus"},
          {id:40011, name:"点亮初宵的奉纳舞", desc:"Yukino Bijin"},
          {id:40012, name:"极快！最快！花之风暴！", desc:"Sakura Bakushin O"},
          {id:50001, name:"Wave of Gratitude", desc:"Fine Motion"},
          {id:50002, name:"7 More Centimeters", desc:"Air Shakur"},
          {id:50003, name:"Hometown Cheers", desc:"Yukino Bijin"},
          {id:50004, name:"My Thoughts, My Desires", desc:"Mejiro Dober"},
          {id:50005, name:"Daring to Dream", desc:"Nice Nature"},
          {id:50006, name:"Paint the Sky Red", desc:"Seiun Sky"},
          {id:50007, name:"Event SSR", desc:"Mihono Bourbon"},
          {id:50008, name:"可爱的你，美丽的你", desc:"Curren Chan"},
          {id:50009, name:"倔强的集市", desc:"Narita Taishin"},
          {id:50010, name:"饱含心意的纸杯蛋糕", desc:"Nishino Flower"},
        ],
      selectedCard: null,
      customCardName: '',
      supportCardTypes: [
        { name: 'speed', img: new URL('../assets/img/support_cards/types/speed.png', import.meta.url).href },
        { name: 'stamina', img: new URL('../assets/img/support_cards/types/stamina.png', import.meta.url).href },
        { name: 'power', img: new URL('../assets/img/support_cards/types/power.png', import.meta.url).href },
        { name: 'will', img: new URL('../assets/img/support_cards/types/will.png', import.meta.url).href },
        { name: 'intelligence', img: new URL('../assets/img/support_cards/types/intelligence.png', import.meta.url).href },
        { name: 'custom', text: 'Custom' }
      ],
      activeType: 'custom',
    }
  },
  computed: {
    isConfirmDisabled() {
      return this.activeType === 'custom' && !this.customCardName.trim();
    },
    filteredSupportCardList() {
      // 根据activeType筛选支援卡
      if (this.activeType === 'speed') {
        return this.umamusumeSupportCardList.filter(card => card.id >= 10000 && card.id < 20000);
      } else if (this.activeType === 'stamina') {
        return this.umamusumeSupportCardList.filter(card => card.id >= 20000 && card.id < 30000);
      } else if (this.activeType === 'power') {
        return this.umamusumeSupportCardList.filter(card => card.id >= 30000 && card.id < 40000);
      } else if (this.activeType === 'will') {
        return this.umamusumeSupportCardList.filter(card => card.id >= 40000 && card.id < 50000);
      } else if (this.activeType === 'intelligence') {
        return this.umamusumeSupportCardList.filter(card => card.id >= 50000 && card.id < 60000);
      } else if (this.activeType === 'custom') {
        return [];
      }
      return [];
    },
    filteredCardImageRows() {
      // 每行8张图片
      const cards = this.filteredSupportCardList;
      const rows = [];
      for (let i = 0; i < cards.length; i += 8) {
        rows.push(cards.slice(i, i + 8));
      }
      return rows;
    },
    cardImageRows() {
      // 每行8张图片
      const cards = this.umamusumeSupportCardList;
      const rows = [];
      for (let i = 0; i < cards.length; i += 8) {
        rows.push(cards.slice(i, i + 8));
      }
      return rows;
    }
  },
  watch: {
    show(newVal) {
      if (newVal) {
        // 显示弹窗
        $('#support-card-select-modal').modal({
          backdrop: 'static',
          keyboard: false,
          show: true
        });
        // 默认选中第一个
        if (!this.selectedCard) {
          this.selectedCard = this.umamusumeSupportCardList[0];
        }
      } else {
        // 隐藏弹窗
        $('#support-card-select-modal').modal('hide');
      }
    }
  },
  methods: {
    handleCancel() {
      this.$emit('update:show', false);
      this.$emit('cancel');
      // 恢复父modal滚动
      this.$nextTick(() => {
        this.restoreParentModalScrolling();
      });
    },
    handleConfirm() {
      if (this.activeType === 'custom') {
        this.$emit('confirm', { name: this.customCardName, id: 'custom' });
      } else {
        this.$emit('confirm', this.selectedCard);
      }
      this.$emit('update:show', false);
      // 恢复父modal滚动
      this.$nextTick(() => {
        this.restoreParentModalScrolling();
      });
    },
    restoreParentModalScrolling() {
      setTimeout(() => {
        if ($('.modal-open').length > 0) {
          $('body').addClass('modal-open');
          const parentModal = $('#create-task-list-modal');
          if (parentModal.hasClass('show')) {
            const modalBody = parentModal.find('.modal-body');
            if (modalBody.length > 0) {
              modalBody.css('overflow-y', 'auto');
              modalBody[0].offsetHeight;
            }
          }
        }
      }, 100);
    },
    getCardImgUrl(id) {
      return new URL(`../assets/img/support_cards/cards/${id}.png`, import.meta.url).href;
    },
    getRarityIcon(rarity){
        // 现在只有SSR
        return new URL('../assets/img/support_cards/rarity/SSR.png', import.meta.url).href;
    },
    handleImgError(event) {
      event.target.src = new URL('../assets/img/support_cards/cards/default.png', import.meta.url).href;
    },
    renderSupportCardText(card) {
      if (!card) return '';
      let type = '';
      if (card.id >= 10000 && card.id < 20000) type = 'Speed';
      else if (card.id >= 20000 && card.id < 30000) type = 'Stamina';
      else if (card.id >= 30000 && card.id < 40000) type = 'Power';
      else if (card.id >= 40000 && card.id < 50000) type = 'Guts';
      else if (card.id >= 50000 && card.id < 60000) type = 'Wit';
      if (type) {
        return `【${card.name}】${type}·${card.desc}`;
      } else {
        return `【${card.name}】${card.desc}`;
      }
    },
    renderSupportCardTextEllipsis(card) {
      if (!card) return '';
      const imgWidth = 120; // px
      const name = card.name;
      // 计算整体宽度
      let totalWidth = 0;
      let charWidth = [];
      for (let i = 0; i < name.length; i++) {
        const width = /[A-Za-z0-9]/.test(name[i]) ? 7 : 13;
        totalWidth += width;
        charWidth.push(width);
      }
      // 如果宽度足够，直接返回
      if (totalWidth <= imgWidth) {
        let type = '';
        if (card.id >= 10000 && card.id < 20000) type = 'Speed';
        else if (card.id >= 20000 && card.id < 30000) type = 'Stamina';
        else if (card.id >= 30000 && card.id < 40000) type = 'Power';
        else if (card.id >= 40000 && card.id < 50000) type = 'Guts';
        else if (card.id >= 50000 && card.id < 60000) type = 'Wit';
        if (type) {
          return `${name}\n${type}·${card.desc}`;
        } else {
          return `${name}\n${card.desc}`;
        }
      }
      // 需要省略
      // 计算省略号宽度
      const ellipsis = '...';
      const ellipsisWidth = 3 * 3;
      // 计算需要去掉多少字符
      let left = Math.ceil(name.length/2)-1;
      let right = name.length - left - 1;

      while (totalWidth + ellipsisWidth > imgWidth){
        totalWidth -= charWidth[left];
        totalWidth -= charWidth[right];
        left--;
        right++;
      }

      const leftStr = name.slice(0, left + 1);
      const rightStr = name.slice(right);
      let type = '';
      if (card.id >= 10000 && card.id < 20000) type = 'Speed';
      else if (card.id >= 20000 && card.id < 30000) type = 'Stamina';
      else if (card.id >= 30000 && card.id < 40000) type = 'Power';
      else if (card.id >= 40000 && card.id < 50000) type = 'Guts';
      else if (card.id >= 50000 && card.id < 60000) type = 'Wit';
      if (type) {
        return `${leftStr}${ellipsis}${rightStr}\n${type}·${card.desc}`;
      } else {
        return `${leftStr}${ellipsis}${rightStr}\n${card.desc}`;
      }
    },
    setActiveType(type) {
      this.activeType = type;
      if (type !== 'custom') {
        this.selectCard(this.filteredSupportCardList[0]);
      }
    },
    getTypeIcon(id) {
      if (id >= 10000 && id < 20000) return new URL('../assets/img/support_cards/types/speed.png', import.meta.url).href;
      if (id >= 20000 && id < 30000) return new URL('../assets/img/support_cards/types/stamina.png', import.meta.url).href;
      if (id >= 30000 && id < 40000) return new URL('../assets/img/support_cards/types/power.png', import.meta.url).href;
      if (id >= 40000 && id < 50000) return new URL('../assets/img/support_cards/types/will.png', import.meta.url).href;
      if (id >= 50000 && id < 60000) return new URL('../assets/img/support_cards/types/intelligence.png', import.meta.url).href;
      return '';
    },
    selectCard(card) {
      this.selectedCard = card;
    },
  },
  mounted() {
    $('#support-card-select-modal').on('hidden.bs.modal', () => {
      this.$emit('update:show', false);
      this.$nextTick(() => {
        this.restoreParentModalScrolling();
      });
    });
  }
}
</script>

<style scoped>
.cancel-btn {
  background-color: #dc3545 !important;
  color: white !important;
  padding: 0.4rem 0.8rem !important;
  font-size: 1rem !important;
  border-radius: 0.25rem;
  border: none;
  cursor: pointer;
  min-width: 60px;
  min-height: 30px;
  font-weight: 500;
}
.cancel-btn:hover {
  background-color: #c82333 !important;
  color: white !important;
}
.auto-btn {
  background: linear-gradient(135deg, var(--accent), var(--accent-2)) !important;
  color: #fff !important;
  padding: 0.4rem 0.8rem !important;
  font-size: 1rem !important;
  border-radius: 0.25rem;
  border: 1px solid var(--accent);
  cursor: pointer;
  min-width: 60px;
  min-height: 30px;
  font-weight: 700;
  box-shadow: 0 4px 12px color-mix(in srgb, var(--accent) 40%, transparent);
}
.auto-btn:hover {
  background: linear-gradient(135deg, var(--accent-2), var(--accent)) !important;
  color: #fff !important;
  transform: translateY(-2px);
  box-shadow: 0 6px 20px color-mix(in srgb, var(--accent) 50%, transparent), 0 0 30px color-mix(in srgb, var(--accent) 30%, transparent);
}
/* 保证弹窗在遮罩层之上 */
#support-card-select-modal.modal {
  z-index: 1060;
}
#support-card-select-modal .modal-dialog {
  z-index: 1061;
}
.section-card{border:1px solid var(--accent);border-radius:12px;box-shadow:none} 
.support-card-modal-body {
  max-height: 600px;
  overflow-y: auto;
  /* 让footer固定时，body不被footer遮挡 */
  padding-bottom: 80px;
}
.support-card-img-grid {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-bottom: 8px;
}
.img-row {
  display: flex;
  flex-direction: row;
  gap: 0px;
  margin-bottom: 0;
}
.img-cell {
  flex: 0 0 12.5%; /* 一行8张图片 */
  display: flex;
  justify-content: center;
  align-items: center;
  min-width: 0;
  padding: 0 2px;
}
.img-content {
  display: flex;
  flex-direction: column;
  align-items: center;
}
.card-img-wrapper {
  position: relative;
  display: inline-block;
}
.card-img-wrapper.selected-card {
  box-shadow: none;
  border-radius: 10px;
}
.card-img-wrapper.selected-card::after {
  content: '';
  position: absolute;
  left: 0; top: 0;
  width: 101%; height: 98%;
  background: rgba(0, 0, 0, 0.5); /* 半透明黑色蒙层 */
  border-radius: 10px;
  z-index: 3;
  pointer-events: none;
}
.card-img-wrapper.selected-card::before {
  content: '';
  position: absolute;
  left: 50%; top: 50%;
  width: 48px;
  height: 36px;
  background: url('/src/assets/img/support_cards/selected_check.svg') center center no-repeat;
  background-size: contain;
  transform: translate(-50%, -50%);
  z-index: 4;
  pointer-events: none;
}
.card-ssr-icon {
  position: absolute;
  top: 6px; /* 往下挪，避免超出图片边界 */
  left: 10px;
  width: 30px;
  height: 30px;
  z-index: 2;
  pointer-events: none;
}
.card-type-icon {
  position: absolute;
  top: 4px; /* 往下挪，避免超出图片边界 */
  right: 2px;
  width: 28px;
  height: 28px;
  z-index: 2;
  pointer-events: none;
}
.support-card-label {
  margin-top: 4px;
  font-size: 0.84rem;
  color: #fff;
  text-align: center;
  word-break: break-all;
  line-height: 1.2;
  max-width: 125px; /* 与图片宽度保持一致 */
  min-height: 1.2em;
  white-space: pre-line;
  overflow: hidden;
  text-overflow: ellipsis;
  display: block;
}
.support-card-img {
  width: 120px;
  height: 160px;
  object-fit: cover;
  border-radius: 8px;
  border: 1px solid var(--accent);
  box-shadow: 0 1px 4px rgba(0,0,0,0.2);
  background: transparent;
  margin-top: 4px;
  margin-bottom: 4px;
  display: block;
}
.type-btn-row {
  display: flex;
  justify-content: flex-start; /* 靠左对齐 */
  align-items: center;
  gap: 8px;
  margin-top: 12px;
  margin-bottom: 8px;
}
.type-btn {
  background: none;
  border: none;
  padding: 0;
  cursor: pointer;
  outline: none;
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
}
/* Allow custom button to size to its text to avoid overlap with neighbors */
.type-btn.custom-btn {
  width: auto;
  height: 40px;
}
.type-btn-img {
  width: 32px;
  height: 32px;
  object-fit: contain;
  display: block;
}
/* remove data-text pseudo label to avoid duplicate text */
/* Custom tab text appearance */
.type-btn-text {
  color: var(--accent);
  font-size: 14px;
  line-height: 32px;
  padding: 0 10px;
  border: 2px solid var(--accent);
  border-radius: 8px;
}
/* When inactive, keep transparent background with pink border and pink text */
.type-btn.custom-btn:not(.active) .type-btn-text {
  background: transparent;
  color: var(--accent);
}
/* When active, solid pink with black text */
.type-btn.custom-btn.active .type-btn-text {
  background: var(--accent);
  color: #000;
}
/* Remove default active background/border for the custom container to avoid double borders */
.type-btn.custom-btn.active {
  background: transparent;
  border-color: transparent;
}
.type-btn-divider {
  border: none;
  border-top: 1px solid var(--accent);
  margin: 0 0 12px 0;
}
.type-btn.active {
  border: 2px solid var(--accent);
  border-radius: 8px;
  background: color-mix(in srgb, var(--accent) 12%, transparent);
}
/* Keep custom inactive button container without default border so only text pill shows border */
.type-btn.custom-btn:not(.active) {
  border: none;
}
.chinese-disclaimer {
  margin-top: 12px;
  font-size: 0.85rem;
  color: var(--accent);
  font-style: italic;
  text-align: center;
  opacity: 0.85;
}
</style>
