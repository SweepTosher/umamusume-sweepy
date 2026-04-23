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
               >
                <div class="img-content">
                  <div
                     class="card-img-wrapper cursor-pointer"
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
          {id:10014, name:"Magical Heroine", desc:"Zenno Rob Roy"},
          {id:10015, name:"Party Formation", desc:"Mayano Top Gun"},
          {id:10016, name:"Searching for Unseen Sights", desc:"Silence Suzuka"},
          {id:10017, name:"Touching Sleeves Is Good Luck! ♪", desc:"Matikanefukukitaru"},
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
          {id:20012, name:"The Whistling Arrow's Taunt", desc:"Narita Brian"},
          {id:20013, name:"My Solo Spun in Spiraling Runs", desc:"Manhattan Cafe"},
          {id:20014, name:"Leaping into the Unknown", desc:"Meisho Doto"},
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
          {id:30011, name:"Beware! Halloween Night!", desc:"Tamamo Cross"},
          {id:30012, name:"Make! Some! NOISE!", desc:"Daitaku Helios"},
          {id:30013, name:"Dazzling Day in the Snow", desc:"Marvelous Sunday"},
          {id:30014, name:"Lucky Star in the Sky", desc:"Admire Vega"},
          {id:30015, name:"A Fan's Joy", desc:"Agnes Digital"},
          {id:40001, name:"The Brightest Star in Japan", desc:"Special Week"},
          {id:40002, name:"Fairest Fleur", desc:"Grass Wonder"},
          {id:40003, name:"Watch My Star Fly!", desc:"Ines Fujin"},
          {id:40004, name:"BNWinner!", desc:"Winning Ticket"},
          {id:40005, name:"Urara's Day Off!", desc:"Haru Urara"},
          {id:40006, name:"Go Ahead and Laugh", desc:"Mejiro Palmer"},
          {id:40007, name:"Just Keep Going", desc:"Matikane Tannhauser"},
          {id:40008, name:"Who Wants the First Bite?", desc:"Hishi Akebono"},
          {id:40009, name:"Winning Pitch", desc:"Mejiro Ryan"},
          {id:40010, name:"Warm Heart, Soft Steps", desc:"Ikuno Dictus"},
          {id:40011, name:"Dancing Light into the Night", desc:"Yukino Bijin"},
          {id:40012, name:"Super! Sonic! Flower Power!", desc:"Sakura Bakushin O"},
          {id:50001, name:"Wave of Gratitude", desc:"Fine Motion"},
          {id:50002, name:"7 More Centimeters", desc:"Air Shakur"},
          {id:50003, name:"Hometown Cheers", desc:"Yukino Bijin"},
          {id:50004, name:"My Thoughts, My Desires", desc:"Mejiro Dober"},
          {id:50005, name:"Daring to Dream", desc:"Nice Nature"},
          {id:50006, name:"Paint the Sky Red", desc:"Seiun Sky"},
          {id:50007, name:"Event SSR", desc:"Mihono Bourbon"},
          {id:50008, name:"Cutie Pie with Shining Eyes", desc:"Curren Chan"},
          {id:50009, name:"Strict Shopper", desc:"Narita Taishin"},
          {id:50010, name:"Even the Littlest Bud", desc:"Nishino Flower"},
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

